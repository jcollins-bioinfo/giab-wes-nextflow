include { INPUT_VALIDATION } from '../input_validation/main'
include { M3_PREFLIGHT } from '../../../modules/local/m3_preflight/main'
include { M3_REFERENCE_FAIDX } from '../../../modules/local/m3_reference_faidx/main'
include { M3_REFERENCE_METADATA } from '../../../modules/local/m3_reference_metadata/main'
include { M3_FASTQ_VALIDATE } from '../../../modules/local/m3_fastq_validate/main'
include { M3_FASTQC } from '../../../modules/local/m3_fastqc/main'
include { M3_BWA_INDEX } from '../../../modules/local/m3_bwa_index/main'
include { M3_ALIGN } from '../../../modules/local/m3_align/main'
include { M3_SORT } from '../../../modules/local/m3_sort/main'
include { M3_MERGE } from '../../../modules/local/m3_merge/main'
include { M3_MARKDUP } from '../../../modules/local/m3_markdup/main'
include { M3_PRE_BQSR } from '../../../modules/local/m3_pre_bqsr/main'
include { M3_RECALIBRATE } from '../../../modules/local/m3_recalibrate/main'
include { M3_APPLY_BQSR } from '../../../modules/local/m3_apply_bqsr/main'
include { M3_BAM_SUMMARY } from '../../../modules/local/m3_bam_summary/main'
include { M3_MOSDEPTH } from '../../../modules/local/m3_mosdepth/main'
include { M3_PICARD_QC } from '../../../modules/local/m3_picard_qc/main'
include { M3_MULTIQC } from '../../../modules/local/m3_multiqc/main'
include { M3_COLLECT } from '../../../modules/local/m3_collect/main'

// M3 qualifies one package-defined invented sample. Canonical inputs never enter this DAG.
workflow M3_SHARED_PREPROCESSING {
    take:
    rows
    samplesheet
    reference
    known_sites
    expectations
    run_meta
    tool_lock
    qc_window
    main:
    INPUT_VALIDATION(rows)
    normalized = INPUT_VALIDATION.out.first()
    lanes = normalized.flatMap { entries ->
        if (entries.collect { item -> item[0].sample }.unique().size() != 1) error 'M3 qualification requires one invented sample'
        entries
    }
    source_reads = normalized.map { entries -> entries.collectMany { item -> item[1] } }
    M3_PREFLIGHT(samplesheet, reference, known_sites, expectations, source_reads, run_meta)
    gate = M3_PREFLIGHT.out.contract
    M3_REFERENCE_FAIDX(reference, gate)
    M3_REFERENCE_METADATA(M3_REFERENCE_FAIDX.out.reference, known_sites)
    prepared_reference = M3_REFERENCE_METADATA.out.reference
    prepared_known_sites = M3_REFERENCE_METADATA.out.known_sites
    prepared_known_sites_index = M3_REFERENCE_METADATA.out.known_sites_index
    M3_BWA_INDEX(reference, gate)
    bwa_index = M3_BWA_INDEX.out.index
    M3_FASTQ_VALIDATE(lanes, prepared_reference, expectations, gate, run_meta)
    M3_FASTQC(M3_FASTQ_VALIDATE.out.reads)
    M3_ALIGN(M3_FASTQ_VALIDATE.out.reads, bwa_index)
    M3_SORT(M3_ALIGN.out.sam)
    sorted_lanes = M3_SORT.out.bams.collect(flat: false).map { entries -> entries.sort { a, b -> a[0].read_group_id <=> b[0].read_group_id } }
    merge_input = sorted_lanes.map { entries -> tuple([id: entries[0][0].sample, sample: entries[0][0].sample], entries.collect { item -> item[2] }) }
    M3_MERGE(merge_input)
    M3_MARKDUP(M3_MERGE.out.bam)
    M3_PRE_BQSR(M3_MARKDUP.out.bam)
    before_bqsr = M3_PRE_BQSR.out.bam
    M3_RECALIBRATE(before_bqsr, prepared_reference, prepared_known_sites, prepared_known_sites_index)
    table = M3_RECALIBRATE.out.table
    apply_input = before_bqsr.combine(table).map { meta, bam, bai, _sam, _duplicates, table_meta, recal_table ->
        if (meta != table_meta) error 'BQSR sample lineage mismatch'
        tuple(meta, bam, bai, recal_table)
    }
    M3_APPLY_BQSR(apply_input, prepared_reference)
    M3_BAM_SUMMARY(M3_APPLY_BQSR.out.bam)
    final_summary = M3_BAM_SUMMARY.out.summary
    shared_bam = final_summary.map { meta, bam, bai, _sam, _header, _flagstat, _idxstats, _stats -> tuple(meta, bam, bai) }
    M3_MOSDEPTH(shared_bam, qc_window)
    M3_PICARD_QC(shared_bam, prepared_reference)
    coverage = M3_MOSDEPTH.out.coverage
    picard = M3_PICARD_QC.out.metrics
    fastqc_reports = M3_FASTQC.out.reports.flatMap { _meta, archives, html -> [archives, html].flatten() }.collect().map { files -> files.sort { a, b -> a.name <=> b.name } }
    lane_reports = M3_FASTQ_VALIDATE.out.reads.map { _meta, _reads, validation -> validation }.collect().map { files -> files.sort { a, b -> a.name <=> b.name } }
    report_sources = fastqc_reports.combine(before_bqsr.map { item -> item[4] }).combine(final_summary.map { item -> [item[5], item[7]] })
        .combine(coverage.map { item -> item[1..3] }).combine(picard.map { item -> item[1] }).map { values -> values.flatten() }
    M3_MULTIQC(report_sources)
    multiqc_html = M3_MULTIQC.out.html
    multiqc_data = M3_MULTIQC.out.data
    qc_sources = M3_MULTIQC.out.source_reports
    stage_inventory = sorted_lanes.map { item -> [entries: item] }.combine(M3_MERGE.out.bam.map { item -> [bam: item[1]] })
        .combine(before_bqsr.map { item -> [bam: item[1]] }).combine(table.map { item -> [table: item[1]] }).map { lane_inventory, merged, before, recal ->
            def paths = lane_inventory.entries.collectMany { item -> [item[1], item[2]] } + [merged.bam, before.bam, recal.table]
            def labels = lane_inventory.entries.collectMany { item -> ['aligned_' + item[0].read_group_id, 'sorted_' + item[0].read_group_id] } + ['merged', 'duplicate_marked', 'recalibration_table']
            tuple(labels, paths)
        }
    tool_versions = M3_BWA_INDEX.out.versions.map { item -> tuple('bwa-mem2', item) }
        .mix(M3_BAM_SUMMARY.out.versions.map { item -> tuple('samtools', item) },
             M3_APPLY_BQSR.out.versions.map { item -> tuple('gatk', item) },
             M3_FASTQC.out.versions.map { item -> tuple('fastqc', item) },
             M3_MOSDEPTH.out.versions.map { item -> tuple('mosdepth', item) },
             M3_MULTIQC.out.versions.map { item -> tuple('multiqc', item) })
        .collect(flat: false).map { records ->
            def distinct = records.sort { a, b -> a[1].name <=> b[1].name }.groupBy { item -> item[0] }.values().collect { item -> item[0] }.sort { a,b -> a[0] <=> b[0] }
            tuple(distinct.collect { item -> item[0] }, distinct.collect { item -> item[1] })
        }
    resource_records = M3_PREFLIGHT.out.resources.mix(M3_REFERENCE_FAIDX.out.resources, M3_REFERENCE_METADATA.out.resources, M3_FASTQ_VALIDATE.out.resources, M3_FASTQC.out.resources, M3_BWA_INDEX.out.resources, M3_ALIGN.out.resources, M3_SORT.out.resources, M3_MERGE.out.resources, M3_MARKDUP.out.resources, M3_PRE_BQSR.out.resources, M3_RECALIBRATE.out.resources, M3_APPLY_BQSR.out.resources, M3_BAM_SUMMARY.out.resources, M3_MOSDEPTH.out.resources, M3_PICARD_QC.out.resources, M3_MULTIQC.out.resources).collect().map { files -> files.sort { a, b -> a.name <=> b.name } }
    commands = M3_PREFLIGHT.out.command.mix(M3_REFERENCE_FAIDX.out.command, M3_REFERENCE_METADATA.out.command, M3_FASTQ_VALIDATE.out.command, M3_FASTQC.out.command, M3_BWA_INDEX.out.command, M3_ALIGN.out.command, M3_SORT.out.command, M3_MERGE.out.command, M3_MARKDUP.out.command, M3_PRE_BQSR.out.command, M3_RECALIBRATE.out.command, M3_APPLY_BQSR.out.command, M3_BAM_SUMMARY.out.command, M3_MOSDEPTH.out.command, M3_PICARD_QC.out.command, M3_MULTIQC.out.command).collect().map { files -> files.sort { a, b -> a.name <=> b.name } }
    extra_inventory = fastqc_reports.map { item -> [files: item] }.combine(coverage.map { item -> [files: item[2..7]] })
        .combine(picard.map { item -> [file: item[1]] }).combine(multiqc_html.map { item -> [file: item] }).map { fastqc, coverage_extra, picard_extra, html ->
            def paths = fastqc.files + coverage_extra.files + [picard_extra.file, html.file]
            tuple(paths.collect { item -> 'qc_' + item.name.replaceAll(/[^A-Za-z0-9_-]/, '_') }, paths)
        }
    M3_COLLECT(final_summary, before_bqsr.map { item -> item[3] }, before_bqsr.map { item -> item[4] }, coverage.map { item -> item[1] },
        gate, expectations, stage_inventory.map { item -> item[1] }, stage_inventory.map { item -> item[0] }, lane_reports,
        tool_versions.map { item -> item[1] }, tool_versions.map { item -> item[0] }, resource_records, commands,
        extra_inventory.map { item -> item[1] }, extra_inventory.map { item -> item[0] }, tool_lock)
    // Nothing is published as an accepted output before the semantic collector succeeds.
    accepted_artifacts = M3_COLLECT.out.contracts.combine(final_summary).combine(before_bqsr.map { item -> item[3] })
        .combine(multiqc_html).combine(multiqc_data).combine(qc_sources).map { values ->
            [values[0], values[2], values[3], values[4], values[9], values[10], values[11], values[12]]
        }.flatMap { item -> item }
    accepted_bam = M3_COLLECT.out.contracts.combine(shared_bam).map { _contract, meta, bam, bai -> tuple(meta, bam, bai) }
    emit:
    bam = accepted_bam
    artifacts = accepted_artifacts
    contracts = M3_COLLECT.out.contracts
}
