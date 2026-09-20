import json
import unittest
from build_public import relative_key, walk


class ExportIdentityTests(unittest.TestCase):
    def test_cloud_scope_redaction_preserves_request_and_attempt_identity(self):
        scope='Z'+':/'+'/'.join(('Users','Synthetic','work','campaign','run-1:jev'))
        original=json.dumps([scope,'jev:example:1',2])
        self.assertEqual(json.loads(relative_key(original)),['campaign/run-1:jev','jev:example:1',2])

    def test_local_reserve_and_complete_join_remains_identical(self):
        identity='Z'+':/'+'/'.join(('Users','Synthetic','campaign','local','telemetry.jsonl:3'))
        self.assertEqual(relative_key(identity),'campaign/local/telemetry.jsonl:3')

    def test_unrecognized_boundary_and_traversal_fail_closed(self):
        for value in ('relative/no-boundary','/campaign/../outside','/campaign/x/campaign/y'):
            with self.assertRaises(ValueError):relative_key(value)

    def test_nested_walk_preserves_numbers_and_records_unambiguous_pointers(self):
        seen=[]
        value={'a/b':[{'~key':2.5},'abc']}
        self.assertEqual(walk(value,lambda v,p:(seen.append(p),v)[1]),value)
        self.assertEqual(seen,['/a~1b/0/~0key','/a~1b/1'])


if __name__=='__main__':unittest.main()
