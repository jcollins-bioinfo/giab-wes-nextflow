process M2_ACQUIRE {
    tag "$run_id"
    label 'process_single'

    input:
    path manifest
    path acquisition_script
    val workspace
    val run_id

    output:
    path 'acquisition.json', emit: observation

    script:
    """
    python ${acquisition_script} --workspace ${workspace} --manifest ${manifest} --run-id ${run_id}
    cp ${workspace}/registry/runs/${run_id}/acquisition.json acquisition.json
    """
}
