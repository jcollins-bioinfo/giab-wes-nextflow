workflow INPUT_VALIDATION {
    take:
    raw_rows
    main:
    normalized = raw_rows.map { rows ->
        def seenRg=[] as Set; def seenPu=[] as Set; def seenRows=[] as Set
        rows.collect { row ->
            def required = ['sample','library','lane','read_group_id','platform_unit','fastq_1','fastq_2']
            required.each { field ->
                if (!row[field]?.toString()?.trim()) error "Missing required field: ${field}"
            }
            ['sample','library','lane','read_group_id','platform_unit'].each { field ->
                if (!(row[field] ==~ /[A-Za-z0-9][A-Za-z0-9._-]*/)) error "Identifier is not URL-safe: ${field}"
            }
            if ((row.platform ?: 'ILLUMINA') != 'ILLUMINA') error 'platform must be ILLUMINA'
            if (row.fastq_1 == row.fastq_2) error 'R1 and R2 must differ'
            if (!row.fastq_1.toString().endsWith('.fastq.gz') || !row.fastq_2.toString().endsWith('.fastq.gz')) error 'mates must end .fastq.gz'
            if (!file(row.fastq_1).exists() || !file(row.fastq_2).exists()) error 'mate is not readable'
            def key = required.collect { field -> row[field] }.join('\u001f')
            if (!seenRows.add(key)) error 'duplicate samplesheet row'
            if (!seenRg.add(row.read_group_id)) error 'duplicate read_group_id'
            if (!seenPu.add(row.platform_unit)) error 'duplicate platform_unit'
            [
              [id:row.sample, sample:row.sample, library:row.library, lane:row.lane,
               read_group_id:row.read_group_id, platform_unit:row.platform_unit,
               sequencing_center:row.sequencing_center ?: null, platform:'ILLUMINA'],
              [file(row.fastq_1, checkIfExists:true), file(row.fastq_2, checkIfExists:true)]
            ]
        }.sort { a,b -> a[0].read_group_id <=> b[0].read_group_id }
    }
    emit:
    normalized
}
