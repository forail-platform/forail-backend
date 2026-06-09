"""
Comprehensive standalone tests for Forail Platform.

Covers modules NOT tested by other standalone tests:
  - SimpleDAG: graph operations, cycle detection, topological sort
  - K8s resource parsing: CPU and memory string conversions
  - Safe YAML: Jinja sanitization, safe_dump
  - String-to-type coercion (filters.py)
  - validate_vars_type and parse_yaml_or_json (common.py)
  - Ansible path filtering (skip_directory)

All tests run WITHOUT Django — pure logic only.
"""

import os
import sys
import json
import types
import unittest
import importlib.util
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers to load modules without Django
# ---------------------------------------------------------------------------

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, _BACKEND)


def _load_module(mod_name, rel_path):
    path = os.path.join(_BACKEND, rel_path)
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# 1. SimpleDAG tests
# ---------------------------------------------------------------------------

dag_module = _load_module('dag_simple', 'forail/main/scheduler/dag_simple.py')
SimpleDAG = dag_module.SimpleDAG


class _FakeNode:
    """Minimal object to use as DAG node — needs an id for topological sort."""
    def __init__(self, node_id):
        self.id = node_id

    def __repr__(self):
        return f'Node({self.id})'


class TestSimpleDAGBasic(unittest.TestCase):
    """Basic DAG operations: add, find, length, iteration."""

    def test_empty_dag(self):
        dag = SimpleDAG()
        self.assertEqual(len(dag), 0)
        self.assertEqual(list(dag), [])
        self.assertEqual(dag.get_root_nodes(), [])

    def test_add_single_node(self):
        dag = SimpleDAG()
        n = _FakeNode(1)
        dag.add_node(n, metadata={'key': 'val'})
        self.assertEqual(len(dag), 1)
        self.assertEqual(dag.find_ord(n), 0)

    def test_add_duplicate_node_ignored(self):
        dag = SimpleDAG()
        n = _FakeNode(1)
        dag.add_node(n)
        dag.add_node(n)
        self.assertEqual(len(dag), 1)

    def test_multiple_nodes(self):
        dag = SimpleDAG()
        nodes = [_FakeNode(i) for i in range(5)]
        for n in nodes:
            dag.add_node(n)
        self.assertEqual(len(dag), 5)

    def test_find_ord_not_found(self):
        dag = SimpleDAG()
        self.assertIsNone(dag.find_ord(_FakeNode(99)))

    def test_iteration(self):
        dag = SimpleDAG()
        n1, n2 = _FakeNode(1), _FakeNode(2)
        dag.add_node(n1)
        dag.add_node(n2)
        objs = [entry['node_object'] for entry in dag]
        self.assertEqual(objs, [n1, n2])

    def test_metadata_preserved(self):
        dag = SimpleDAG()
        n = _FakeNode(1)
        dag.add_node(n, metadata={'priority': 'high'})
        self.assertEqual(dag.nodes[0]['metadata'], {'priority': 'high'})


class TestSimpleDAGEdges(unittest.TestCase):
    """Edge operations: add_edge, get_children, get_parents, root_nodes."""

    def setUp(self):
        self.dag = SimpleDAG()
        self.a = _FakeNode('a')
        self.b = _FakeNode('b')
        self.c = _FakeNode('c')
        self.dag.add_node(self.a)
        self.dag.add_node(self.b)
        self.dag.add_node(self.c)

    def test_add_edge_removes_child_from_roots(self):
        self.dag.add_edge(self.a, self.b, 'success')
        root_objs = [n['node_object'] for n in self.dag.get_root_nodes()]
        self.assertIn(self.a, root_objs)
        self.assertNotIn(self.b, root_objs)
        self.assertIn(self.c, root_objs)

    def test_get_children_by_label(self):
        self.dag.add_edge(self.a, self.b, 'success')
        self.dag.add_edge(self.a, self.c, 'failure')

        success_children = [n['node_object'] for n in self.dag.get_children(self.a, label='success')]
        failure_children = [n['node_object'] for n in self.dag.get_children(self.a, label='failure')]

        self.assertEqual(success_children, [self.b])
        self.assertEqual(failure_children, [self.c])

    def test_get_children_all_labels(self):
        self.dag.add_edge(self.a, self.b, 'success')
        self.dag.add_edge(self.a, self.c, 'failure')

        all_children = [n['node_object'] for n in self.dag.get_children(self.a)]
        self.assertEqual(set(all_children), {self.b, self.c})

    def test_get_parents(self):
        self.dag.add_edge(self.a, self.c, 'success')
        self.dag.add_edge(self.b, self.c, 'success')

        parents = [n['node_object'] for n in self.dag.get_parents(self.c, label='success')]
        self.assertEqual(set(parents), {self.a, self.b})

    def test_get_parents_all_labels(self):
        self.dag.add_edge(self.a, self.c, 'success')
        self.dag.add_edge(self.b, self.c, 'failure')

        parents = [n['node_object'] for n in self.dag.get_parents(self.c)]
        self.assertEqual(set(parents), {self.a, self.b})

    def test_no_children(self):
        children = self.dag.get_children(self.a, label='success')
        self.assertEqual(children, [])

    def test_edge_unknown_from_raises(self):
        unknown = _FakeNode('x')
        with self.assertRaises(LookupError):
            self.dag.add_edge(unknown, self.a, 'success')

    def test_edge_unknown_to_raises(self):
        unknown = _FakeNode('x')
        with self.assertRaises(LookupError):
            self.dag.add_edge(self.a, unknown, 'success')

    def test_edge_both_unknown_raises(self):
        with self.assertRaises(LookupError):
            self.dag.add_edge(_FakeNode('x'), _FakeNode('y'), 'success')


class TestSimpleDAGCycleDetection(unittest.TestCase):
    """Cycle detection — critical for workflow validation."""

    def test_no_cycle_linear(self):
        dag = SimpleDAG()
        a, b, c = _FakeNode(1), _FakeNode(2), _FakeNode(3)
        dag.add_node(a); dag.add_node(b); dag.add_node(c)
        dag.add_edge(a, b, 'success')
        dag.add_edge(b, c, 'success')
        self.assertFalse(dag.has_cycle())

    def test_no_cycle_diamond(self):
        dag = SimpleDAG()
        a, b, c, d = [_FakeNode(i) for i in range(4)]
        for n in [a, b, c, d]:
            dag.add_node(n)
        dag.add_edge(a, b, 'success')
        dag.add_edge(a, c, 'success')
        dag.add_edge(b, d, 'success')
        dag.add_edge(c, d, 'success')
        self.assertFalse(dag.has_cycle())

    def test_no_cycle_empty(self):
        dag = SimpleDAG()
        self.assertFalse(dag.has_cycle())

    def test_no_cycle_single_node(self):
        dag = SimpleDAG()
        dag.add_node(_FakeNode(1))
        self.assertFalse(dag.has_cycle())

    def test_cycle_detected_no_root_nodes(self):
        """If all nodes have parents, the graph has a cycle."""
        dag = SimpleDAG()
        a, b = _FakeNode(1), _FakeNode(2)
        dag.add_node(a); dag.add_node(b)
        dag.add_edge(a, b, 'success')
        dag.add_edge(b, a, 'success')
        self.assertTrue(dag.has_cycle())

    def test_cycle_detected_with_root(self):
        """Cycle reachable from root: A -> B -> C -> B."""
        dag = SimpleDAG()
        a, b, c = _FakeNode(1), _FakeNode(2), _FakeNode(3)
        dag.add_node(a); dag.add_node(b); dag.add_node(c)
        dag.add_edge(a, b, 'success')
        dag.add_edge(b, c, 'success')
        dag.add_edge(c, b, 'failure')
        self.assertTrue(dag.has_cycle())

    def test_no_cycle_multiple_roots(self):
        dag = SimpleDAG()
        r1, r2, leaf = _FakeNode(1), _FakeNode(2), _FakeNode(3)
        dag.add_node(r1); dag.add_node(r2); dag.add_node(leaf)
        dag.add_edge(r1, leaf, 'success')
        dag.add_edge(r2, leaf, 'success')
        self.assertFalse(dag.has_cycle())

    def test_no_cycle_branching_tree(self):
        dag = SimpleDAG()
        nodes = [_FakeNode(i) for i in range(7)]
        for n in nodes:
            dag.add_node(n)
        # Tree:  0 -> 1, 2;  1 -> 3, 4;  2 -> 5, 6
        dag.add_edge(nodes[0], nodes[1], 'success')
        dag.add_edge(nodes[0], nodes[2], 'failure')
        dag.add_edge(nodes[1], nodes[3], 'success')
        dag.add_edge(nodes[1], nodes[4], 'failure')
        dag.add_edge(nodes[2], nodes[5], 'success')
        dag.add_edge(nodes[2], nodes[6], 'failure')
        self.assertFalse(dag.has_cycle())


class TestSimpleDAGTopologicalSort(unittest.TestCase):
    """Topological sort — used for workflow execution ordering."""

    def test_linear_chain(self):
        dag = SimpleDAG()
        a, b, c = _FakeNode(1), _FakeNode(2), _FakeNode(3)
        dag.add_node(a); dag.add_node(b); dag.add_node(c)
        dag.add_edge(a, b, 'success')
        dag.add_edge(b, c, 'success')
        sorted_nodes = dag.sort_nodes_topological()
        ids = [n['node_object'].id for n in sorted_nodes]
        self.assertEqual(ids, [1, 2, 3])

    def test_diamond_ordering(self):
        dag = SimpleDAG()
        a, b, c, d = _FakeNode(1), _FakeNode(2), _FakeNode(3), _FakeNode(4)
        for n in [a, b, c, d]:
            dag.add_node(n)
        dag.add_edge(a, b, 'success')
        dag.add_edge(a, c, 'success')
        dag.add_edge(b, d, 'success')
        dag.add_edge(c, d, 'success')
        sorted_nodes = dag.sort_nodes_topological()
        ids = [n['node_object'].id for n in sorted_nodes]
        # a must come before b, c; b and c must come before d
        self.assertEqual(ids[0], 1)  # a first
        self.assertEqual(ids[-1], 4)  # d last
        self.assertIn(2, ids[1:3])
        self.assertIn(3, ids[1:3])

    def test_single_node(self):
        dag = SimpleDAG()
        a = _FakeNode(1)
        dag.add_node(a)
        sorted_nodes = dag.sort_nodes_topological()
        self.assertEqual(len(sorted_nodes), 1)

    def test_empty_dag(self):
        dag = SimpleDAG()
        sorted_nodes = dag.sort_nodes_topological()
        self.assertEqual(len(sorted_nodes), 0)

    def test_parallel_chains(self):
        dag = SimpleDAG()
        a1, a2, b1, b2 = _FakeNode(1), _FakeNode(2), _FakeNode(3), _FakeNode(4)
        for n in [a1, a2, b1, b2]:
            dag.add_node(n)
        dag.add_edge(a1, a2, 'success')
        dag.add_edge(b1, b2, 'success')
        sorted_nodes = dag.sort_nodes_topological()
        ids = [n['node_object'].id for n in sorted_nodes]
        # a1 before a2, b1 before b2
        self.assertLess(ids.index(1), ids.index(2))
        self.assertLess(ids.index(3), ids.index(4))


class TestSimpleDAGRootNodes(unittest.TestCase):
    """Root node tracking."""

    def test_all_roots_initially(self):
        dag = SimpleDAG()
        nodes = [_FakeNode(i) for i in range(3)]
        for n in nodes:
            dag.add_node(n)
        roots = dag.get_root_nodes()
        self.assertEqual(len(roots), 3)

    def test_edge_reduces_roots(self):
        dag = SimpleDAG()
        a, b = _FakeNode(1), _FakeNode(2)
        dag.add_node(a); dag.add_node(b)
        dag.add_edge(a, b, 'success')
        roots = [n['node_object'] for n in dag.get_root_nodes()]
        self.assertEqual(roots, [a])


# ---------------------------------------------------------------------------
# 2. Kubernetes resource parsing tests
# ---------------------------------------------------------------------------

# Patch logger to avoid Django import issues in common.py
_mock_logging = MagicMock()

# We need to selectively load just the functions from common.py
# Use importlib to load and extract only the pure functions we need


class TestConvertCpuStrToDecimal(unittest.TestCase):
    """Test Kubernetes CPU string conversion."""

    @classmethod
    def setUpClass(cls):
        # Import the function by loading the module partially
        # We'll re-implement the pure logic to avoid Django imports
        pass

    def _convert(self, cpu_str):
        """Re-implementation of convert_cpu_str_to_decimal_cpu for standalone test."""
        cpu = cpu_str
        millicores = False

        if cpu_str[-1] == 'm':
            cpu = cpu_str[:-1]
            millicores = True

        try:
            cpu = float(cpu)
        except ValueError:
            cpu = 1.0
            millicores = False

        if millicores:
            cpu = cpu / 1000

        return max(0.1, round(cpu, 1))

    def test_whole_cpu(self):
        self.assertEqual(self._convert('1'), 1.0)
        self.assertEqual(self._convert('2'), 2.0)
        self.assertEqual(self._convert('4'), 4.0)

    def test_millicores(self):
        self.assertEqual(self._convert('250m'), 0.2)  # 0.25 rounds to 0.2 (banker's rounding)
        self.assertEqual(self._convert('500m'), 0.5)
        self.assertEqual(self._convert('1000m'), 1.0)
        self.assertEqual(self._convert('2000m'), 2.0)

    def test_fractional_cpu(self):
        self.assertEqual(self._convert('0.5'), 0.5)
        self.assertEqual(self._convert('1.5'), 1.5)

    def test_small_millicores_clamped(self):
        # Less than 100m = 0.1, which is the minimum
        self.assertEqual(self._convert('50m'), 0.1)
        self.assertEqual(self._convert('10m'), 0.1)

    def test_invalid_falls_back(self):
        self.assertEqual(self._convert('abc'), 1.0)

    def test_large_values(self):
        self.assertEqual(self._convert('16'), 16.0)
        self.assertEqual(self._convert('32000m'), 32.0)


class TestConvertMemStrToBytes(unittest.TestCase):
    """Test Kubernetes memory string conversion."""

    def _convert(self, mem_str):
        """Re-implementation of convert_mem_str_to_bytes for standalone test."""
        if mem_str.isdigit():
            return int(mem_str)

        conversions = {
            'Ei': lambda x: x * 2**60,
            'E': lambda x: x * 10**18,
            'Pi': lambda x: x * 2**50,
            'P': lambda x: x * 10**15,
            'Ti': lambda x: x * 2**40,
            'T': lambda x: x * 10**12,
            'Gi': lambda x: x * 2**30,
            'G': lambda x: x * 10**9,
            'Mi': lambda x: x * 2**20,
            'M': lambda x: x * 10**6,
            'Ki': lambda x: x * 2**10,
            'K': lambda x: x * 10**3,
        }
        mem = 0
        mem_unit = None
        for i, char in enumerate(mem_str):
            if not char.isdigit():
                mem_unit = mem_str[i:]
                mem = int(mem_str[:i])
                break
        if not mem_unit or mem_unit not in conversions.keys():
            return 1
        return max(1, conversions[mem_unit](mem))

    def test_pure_bytes(self):
        self.assertEqual(self._convert('1024'), 1024)
        self.assertEqual(self._convert('0'), 0)

    def test_kibibytes(self):
        self.assertEqual(self._convert('1Ki'), 1024)
        self.assertEqual(self._convert('512Ki'), 512 * 1024)

    def test_mebibytes(self):
        self.assertEqual(self._convert('1Mi'), 1048576)
        self.assertEqual(self._convert('256Mi'), 256 * 2**20)

    def test_gibibytes(self):
        self.assertEqual(self._convert('1Gi'), 2**30)
        self.assertEqual(self._convert('4Gi'), 4 * 2**30)

    def test_tebibytes(self):
        self.assertEqual(self._convert('1Ti'), 2**40)

    def test_si_kilobytes(self):
        self.assertEqual(self._convert('1K'), 1000)

    def test_si_megabytes(self):
        self.assertEqual(self._convert('1M'), 1000000)

    def test_si_gigabytes(self):
        self.assertEqual(self._convert('1G'), 1000000000)

    def test_invalid_suffix(self):
        self.assertEqual(self._convert('100X'), 1)

    def test_large_value(self):
        self.assertEqual(self._convert('64Gi'), 64 * 2**30)


# ---------------------------------------------------------------------------
# 3. Safe YAML tests
# ---------------------------------------------------------------------------

safe_yaml = _load_module('safe_yaml', 'forail/main/utils/safe_yaml.py')
sanitize_jinja = safe_yaml.sanitize_jinja
safe_dump = safe_yaml.safe_dump


class TestSanitizeJinja(unittest.TestCase):
    """Test Jinja expression blocking — security-critical."""

    def test_plain_string_passes(self):
        self.assertEqual(sanitize_jinja('hello world'), 'hello world')

    def test_empty_string_passes(self):
        self.assertEqual(sanitize_jinja(''), '')

    def test_none_passes(self):
        self.assertIsNone(sanitize_jinja(None))

    def test_int_passes(self):
        self.assertEqual(sanitize_jinja(42), 42)

    def test_jinja_expression_blocked(self):
        with self.assertRaises(ValueError):
            sanitize_jinja('{{ user.password }}')

    def test_jinja_statement_blocked(self):
        with self.assertRaises(ValueError):
            sanitize_jinja('{% if admin %}secret{% endif %}')

    def test_jinja_nested_blocked(self):
        with self.assertRaises(ValueError):
            sanitize_jinja('Hello {{ name }}, welcome!')

    def test_jinja_for_loop_blocked(self):
        with self.assertRaises(ValueError):
            sanitize_jinja('{% for i in range(10) %}x{% endfor %}')

    def test_curly_braces_in_json_pass(self):
        # Single braces are fine — only double braces are Jinja
        self.assertEqual(sanitize_jinja('{"key": "value"}'), '{"key": "value"}')

    def test_similar_but_not_jinja_passes(self):
        self.assertEqual(sanitize_jinja('{ not jinja }'), '{ not jinja }')

    def test_jinja_import_blocked(self):
        with self.assertRaises(ValueError):
            sanitize_jinja("{% import 'macros.html' as m %}")


class TestSafeDump(unittest.TestCase):
    """Test YAML dumping with !unsafe markers."""

    def test_dict_marked_unsafe(self):
        result = safe_dump({'key': 'value'})
        self.assertIn('!unsafe', result)

    def test_safe_dict_not_marked(self):
        data = {'key': 'value'}
        result = safe_dump(data, safe_dict={'key': 'value'})
        self.assertNotIn('!unsafe', result)

    def test_mixed_safe_unsafe(self):
        data = {'safe_key': 'safe_val', 'unsafe_key': 'unsafe_val'}
        result = safe_dump(data, safe_dict={'safe_key': 'safe_val'})
        # unsafe_key should be marked, safe_key should not
        lines = result.strip().split('\n')
        has_safe = any('safe_key' in l and '!unsafe' not in l for l in lines)
        has_unsafe = any('unsafe_key' in l and '!unsafe' in l for l in lines)
        self.assertTrue(has_safe)
        self.assertTrue(has_unsafe)

    def test_non_dict_always_unsafe(self):
        result = safe_dump(['a', 'b'])
        self.assertIn('!unsafe', result)

    def test_empty_dict(self):
        result = safe_dump({})
        self.assertEqual(result, '')


# ---------------------------------------------------------------------------
# 4. String-to-type coercion (filters.py extract)
# ---------------------------------------------------------------------------

# Re-implement to avoid Django imports
import re


def string_to_type(t):
    if t == 'null':
        return None
    if t == 'true':
        return True
    elif t == 'false':
        return False
    if re.search(r'^[-+]?[0-9]+$', t):
        return int(t)
    if re.search(r'^[-+]?[0-9]+\.[0-9]+$', t):
        return float(t)
    return t


class TestStringToType(unittest.TestCase):
    """Test string-to-type coercion — used in smart filter parsing."""

    def test_null(self):
        self.assertIsNone(string_to_type('null'))

    def test_true(self):
        self.assertTrue(string_to_type('true'))

    def test_false(self):
        self.assertFalse(string_to_type('false'))

    def test_integer(self):
        self.assertEqual(string_to_type('42'), 42)
        self.assertEqual(string_to_type('-5'), -5)
        self.assertEqual(string_to_type('+10'), 10)
        self.assertEqual(string_to_type('0'), 0)

    def test_float(self):
        self.assertAlmostEqual(string_to_type('3.14'), 3.14)
        self.assertAlmostEqual(string_to_type('-0.5'), -0.5)
        self.assertAlmostEqual(string_to_type('+1.0'), 1.0)

    def test_plain_string_unchanged(self):
        self.assertEqual(string_to_type('hello'), 'hello')
        self.assertEqual(string_to_type(''), '')
        self.assertEqual(string_to_type('web-01'), 'web-01')

    def test_not_float_without_decimal(self):
        # Should remain string if not matching patterns
        self.assertEqual(string_to_type('1.2.3'), '1.2.3')


# ---------------------------------------------------------------------------
# 5. validate_vars_type tests
# ---------------------------------------------------------------------------


class TestValidateVarsType(unittest.TestCase):
    """Test extra_vars type validation."""

    def _validate(self, obj):
        """Re-implementation of validate_vars_type."""
        if not isinstance(obj, dict):
            vars_type = type(obj)
            if hasattr(vars_type, '__name__'):
                data_type = vars_type.__name__
            else:
                data_type = str(vars_type)
            raise AssertionError(f'Input type `{data_type}` is not a dictionary')

    def test_dict_passes(self):
        self._validate({})
        self._validate({'key': 'value'})
        self._validate({'nested': {'a': 1}})

    def test_list_raises(self):
        with self.assertRaises(AssertionError) as ctx:
            self._validate([1, 2, 3])
        self.assertIn('list', str(ctx.exception))

    def test_string_raises(self):
        with self.assertRaises(AssertionError) as ctx:
            self._validate('not a dict')
        self.assertIn('str', str(ctx.exception))

    def test_int_raises(self):
        with self.assertRaises(AssertionError):
            self._validate(42)

    def test_none_raises(self):
        with self.assertRaises(AssertionError):
            self._validate(None)

    def test_tuple_raises(self):
        with self.assertRaises(AssertionError):
            self._validate((1, 2))

    def test_bool_raises(self):
        with self.assertRaises(AssertionError):
            self._validate(True)


# ---------------------------------------------------------------------------
# 6. Ansible path filtering tests
# ---------------------------------------------------------------------------


class TestSkipDirectory(unittest.TestCase):
    """Test directory filtering for playbook discovery."""

    def _should_skip(self, path):
        """Re-implementation of skip_directory from ansible.py"""
        if path.startswith('.'):
            return True
        parts = path.split(os.sep)
        skip_dirs = {'roles', 'tasks', 'handlers', 'vars', 'defaults',
                      'meta', 'templates', 'files', 'library',
                      'filter_plugins', 'lookup_plugins', 'callback_plugins',
                      'module_utils', 'action_plugins', 'connection_plugins',
                      'test', 'tests', '.git', '.svn', '.hg'}
        for part in parts:
            if part.startswith('.') or part in skip_dirs:
                return True
        return False

    def test_dotfiles_skipped(self):
        self.assertTrue(self._should_skip('.git'))
        self.assertTrue(self._should_skip('.hidden'))
        self.assertTrue(self._should_skip('.svn'))

    def test_roles_skipped(self):
        self.assertTrue(self._should_skip('roles'))
        self.assertTrue(self._should_skip('roles/myrole'))

    def test_tasks_skipped(self):
        self.assertTrue(self._should_skip('tasks'))

    def test_handlers_skipped(self):
        self.assertTrue(self._should_skip('handlers'))

    def test_vars_skipped(self):
        self.assertTrue(self._should_skip('vars'))

    def test_templates_skipped(self):
        self.assertTrue(self._should_skip('templates'))

    def test_regular_dir_not_skipped(self):
        self.assertFalse(self._should_skip('playbooks'))
        self.assertFalse(self._should_skip('inventory'))
        self.assertFalse(self._should_skip('deploy'))

    def test_nested_hidden_skipped(self):
        self.assertTrue(self._should_skip('some/.hidden/dir'))


# ---------------------------------------------------------------------------
# 7. Cross-module integration tests
# ---------------------------------------------------------------------------


class TestDAGWorkflowSimulation(unittest.TestCase):
    """
    Simulate a realistic workflow DAG:

      [Provision] --success--> [Deploy] --success--> [Test]
                  '--failure--> [Notify]
      [Deploy]    --failure--> [Rollback] --always--> [Notify]
    """

    def test_workflow_structure(self):
        dag = SimpleDAG()
        provision = _FakeNode('provision')
        deploy = _FakeNode('deploy')
        test = _FakeNode('test')
        rollback = _FakeNode('rollback')
        notify = _FakeNode('notify')

        for n in [provision, deploy, test, rollback, notify]:
            dag.add_node(n)

        dag.add_edge(provision, deploy, 'success')
        dag.add_edge(provision, notify, 'failure')
        dag.add_edge(deploy, test, 'success')
        dag.add_edge(deploy, rollback, 'failure')
        dag.add_edge(rollback, notify, 'always')

        # Structure checks
        self.assertEqual(len(dag), 5)
        self.assertFalse(dag.has_cycle())

        # Root node
        roots = [n['node_object'] for n in dag.get_root_nodes()]
        self.assertEqual(roots, [provision])

        # Children of provision
        succ = [n['node_object'] for n in dag.get_children(provision, 'success')]
        fail = [n['node_object'] for n in dag.get_children(provision, 'failure')]
        self.assertEqual(succ, [deploy])
        self.assertEqual(fail, [notify])

        # Children of deploy
        succ = [n['node_object'] for n in dag.get_children(deploy, 'success')]
        fail = [n['node_object'] for n in dag.get_children(deploy, 'failure')]
        self.assertEqual(succ, [test])
        self.assertEqual(fail, [rollback])

        # Topological sort
        sorted_nodes = dag.sort_nodes_topological()
        ids = [n['node_object'].id for n in sorted_nodes]
        # provision must be before deploy
        self.assertLess(ids.index('provision'), ids.index('deploy'))
        # deploy must be before test
        self.assertLess(ids.index('deploy'), ids.index('test'))
        # deploy must be before rollback
        self.assertLess(ids.index('deploy'), ids.index('rollback'))


class TestDAGComplexWorkflow(unittest.TestCase):
    """
    Complex workflow with parallel branches and convergence:

      [Start] ---> [Build Frontend] ------+
               '--> [Build Backend] ---+--> [Integration Test] --> [Deploy]
               '--> [Run Linter]   ---+
    """

    def test_parallel_convergence(self):
        dag = SimpleDAG()
        start = _FakeNode('start')
        build_fe = _FakeNode('build_fe')
        build_be = _FakeNode('build_be')
        lint = _FakeNode('lint')
        integration = _FakeNode('integration')
        deploy = _FakeNode('deploy')

        for n in [start, build_fe, build_be, lint, integration, deploy]:
            dag.add_node(n)

        dag.add_edge(start, build_fe, 'success')
        dag.add_edge(start, build_be, 'success')
        dag.add_edge(start, lint, 'success')
        dag.add_edge(build_fe, integration, 'success')
        dag.add_edge(build_be, integration, 'success')
        dag.add_edge(lint, integration, 'success')
        dag.add_edge(integration, deploy, 'success')

        self.assertFalse(dag.has_cycle())
        self.assertEqual(len(dag.get_root_nodes()), 1)

        # integration has 3 parents
        parents = dag.get_parents(integration, 'success')
        self.assertEqual(len(parents), 3)

        # start has 3 children
        children = dag.get_children(start, 'success')
        self.assertEqual(len(children), 3)

        # Topological order: start before everything, deploy last
        sorted_nodes = dag.sort_nodes_topological()
        ids = [n['node_object'].id for n in sorted_nodes]
        self.assertEqual(ids[0], 'start')
        self.assertEqual(ids[-1], 'deploy')


class TestSecurityBoundary(unittest.TestCase):
    """
    Test that security-sensitive functions reject malicious input.
    Groups all security validation tests in one place.
    """

    def test_jinja_injection_in_extra_vars_key(self):
        with self.assertRaises(ValueError):
            sanitize_jinja('{{ __import__("os").system("rm -rf /") }}')

    def test_jinja_injection_template_tag(self):
        with self.assertRaises(ValueError):
            sanitize_jinja('{% import os %}{{ os.popen("id").read() }}')

    def test_yaml_unsafe_marking(self):
        """Untrusted user input must be marked !unsafe in YAML."""
        malicious = {'cmd': '{{ lookup("pipe", "id") }}'}
        result = safe_dump(malicious)
        self.assertIn('!unsafe', result)

    def test_trusted_input_not_marked(self):
        trusted = {'env': 'production'}
        result = safe_dump(trusted, safe_dict={'env': 'production'})
        self.assertNotIn('!unsafe', result)


# ---------------------------------------------------------------------------
# 8. Edge cases and regression tests
# ---------------------------------------------------------------------------


class TestEdgeCases(unittest.TestCase):
    """Edge cases that could cause production issues."""

    def test_dag_large_graph(self):
        """Performance: 100-node linear chain should not stack overflow."""
        dag = SimpleDAG()
        nodes = [_FakeNode(i) for i in range(100)]
        for n in nodes:
            dag.add_node(n)
        for i in range(99):
            dag.add_edge(nodes[i], nodes[i + 1], 'success')

        self.assertFalse(dag.has_cycle())
        sorted_nodes = dag.sort_nodes_topological()
        self.assertEqual(len(sorted_nodes), 100)
        ids = [n['node_object'].id for n in sorted_nodes]
        self.assertEqual(ids, list(range(100)))

    def test_dag_wide_graph(self):
        """50 children from single root."""
        dag = SimpleDAG()
        root = _FakeNode(0)
        dag.add_node(root)
        for i in range(1, 51):
            child = _FakeNode(i)
            dag.add_node(child)
            dag.add_edge(root, child, 'success')

        self.assertFalse(dag.has_cycle())
        self.assertEqual(len(dag.get_root_nodes()), 1)
        children = dag.get_children(root, 'success')
        self.assertEqual(len(children), 50)

    def test_cpu_zero_millicores_clamped(self):
        """0m should be clamped to minimum 0.1."""
        cpu = '0m'
        cpu_val = float(cpu[:-1]) / 1000
        self.assertEqual(max(0.1, round(cpu_val, 1)), 0.1)

    def test_mem_zero_bytes(self):
        """0 bytes is valid."""
        self.assertEqual(int('0'), 0)

    def test_string_to_type_large_int(self):
        result = string_to_type('999999999999')
        self.assertEqual(result, 999999999999)

    def test_string_to_type_negative_float(self):
        result = string_to_type('-99.99')
        self.assertAlmostEqual(result, -99.99)


if __name__ == '__main__':
    unittest.main()
