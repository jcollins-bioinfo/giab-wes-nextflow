"""Descriptive recalibrated-base coverage on the preregistered evaluation domain."""
from __future__ import annotations

from itertools import zip_longest
from pathlib import Path
import shutil
from typing import Any, Iterable

from .canonical_science import Commands, CONTIGS, file_id, indexed_reference, stage_file, write_json
from .coding_domain import EXPECTED, assert_domain, load_bed
from .m5 import require

DEFINITION = ('Depth of recalibrated shared-BAM bases in the fixed R_eval_holdout domain: '
              'base quality >=20, mapping quality >=20; overlapping mates counted once; '
              'UNMAP, SECONDARY, QCFAIL, DUP and SUPPLEMENTARY records excluded. '
              'Zero-depth bases are included. Descriptive coverage does not redefine accuracy denominators.')


def summarize_depth(lines: Iterable[str], intervals: list[tuple[str, int, int]]) -> dict[str, Any]:
    """Stream exact BED positions against depth rows; reject missing/extra/repeated bases."""
    expected = ((chrom, position) for chrom, start, end in intervals for position in range(start + 1, end + 1))
    counts = {str(threshold): 0 for threshold in (1, 10, 20, 30)}
    total, depth_sum = 0, 0
    for coordinate, line in zip_longest(expected, lines):
        require(coordinate is not None and line is not None, 'coverage has missing or extra positions')
        fields = line.rstrip('\n').split('\t')
        require(len(fields) == 3 and fields[1].isdigit() and fields[2].isdigit(), 'malformed depth row')
        require((fields[0], int(fields[1])) == coordinate, 'coverage position order/duplicate mismatch')
        depth = int(fields[2]); total += 1; depth_sum += depth
        for threshold in counts:
            counts[threshold] += depth >= int(threshold)
    require(total > 0, 'empty coverage domain')
    return {'evaluated_bases': total, 'covered_bases': counts['1'], 'bases_at_least': counts,
            'depth_sum': depth_sum, 'mean_depth': depth_sum / total}


def coverage(runtime: Any, shared: Path, evaluation: Path, output: Path) -> dict[str, Any]:
    """Run pinned samtools depth after calling, admitting no truth or caller-result inputs."""
    require(file_id(evaluation)['sha256'] == EXPECTED['R_eval_holdout'][2], 'unapproved coverage evaluation domain')
    seqs = indexed_reference(shared / 'reference.fa')
    lengths = {name: len(sequence) for name, sequence in seqs.items()}
    intervals = load_bed(evaluation, lengths, CONTIGS)
    assert_domain(intervals, lengths)
    require(len(intervals) == EXPECTED['R_eval_holdout'][0] and sum(end-start for _, start, end in intervals) == EXPECTED['R_eval_holdout'][1], 'coverage domain counts differ from approved domain')
    output.mkdir(parents=True, exist_ok=True)
    task = output / 'active'; commands = Commands(runtime, task, 'common_downstream')
    for source, name in ((shared / 'shared.bam', 'shared.bam'), (shared / 'shared.bam.bai', 'shared.bam.bai'), (evaluation, 'evaluation.bed')):
        stage_file(source, task / name)
    commands.run('samtools', ['depth', '-aa', '-b', 'evaluation.bed', '-q', '20', '-Q', '20', '-s',
                              '-G', 'UNMAP,SECONDARY,QCFAIL,DUP,SUPPLEMENTARY', '-o', 'depth.tsv', 'shared.bam'])
    with (task / 'depth.tsv').open() as stream:
        summary = summarize_depth(stream, intervals)
    require(summary['evaluated_bases'] == EXPECTED['R_eval_holdout'][1], 'coverage denominator mismatch')
    private_depth = output / 'depth.tsv'
    (task / 'depth.tsv').replace(private_depth)
    artifact = file_id(private_depth)
    public = {'kind': 'coverage', 'status': 'passed', **summary, 'definition': DEFINITION,
              'artifact': artifact, 'domain_id': 'R_eval_holdout', 'domain_sha256': file_id(evaluation)['sha256'],
              'shared_bam_sha256': file_id(shared / 'shared.bam')['sha256'],
              'tool': {'name': 'samtools', 'version': '1.24', 'image': commands.records[0]['image']},
              'parameters': {'base_quality_minimum': 20, 'mapping_quality_minimum': 20, 'overlapping_mates': 'count_once_first_read',
                             'excluded_flags': ['UNMAP', 'SECONDARY', 'QCFAIL', 'DUP', 'SUPPLEMENTARY'], 'zero_depth_bases': True},
              'interpretation': 'descriptive; coverage does not condition the benchmark denominator'}
    write_json(output / 'public-coverage.json', public)
    write_json(output / 'receipt.json', {**public, 'commands': commands.records})
    shutil.rmtree(task)
    return {**public, 'commands': commands.records}
