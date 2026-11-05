import hashlib,json
from tools.l3_matrix_collection import confirmed_submission_block

def test_only_reviewed_unchanged_submission_is_blocked(tmp_path):
 folder=tmp_path/'eval';folder.mkdir();trial=tmp_path/'trial';trial.mkdir()
 manifest=trial/'submission-manifest.json';manifest.write_text('frozen')
 assert not confirmed_submission_block(folder,trial)
 block={'kind':'confirmed_submission_failure','manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest()}
 (folder/'collection-block.json').write_text(json.dumps(block))
 assert confirmed_submission_block(folder,trial)
 manifest.write_text('different')
 assert not confirmed_submission_block(folder,trial)
def test_infrastructure_failure_never_blocked(tmp_path):
 (tmp_path/'submission-manifest.json').write_text('frozen')
 (tmp_path/'collection-block.json').write_text(json.dumps({'kind':'infrastructure_failure','manifest_sha256':hashlib.sha256(b'frozen').hexdigest()}))
 assert not confirmed_submission_block(tmp_path,tmp_path)
