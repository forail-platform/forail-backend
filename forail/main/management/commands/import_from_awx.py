"""
import_from_awx — one-shot migration of configuration from an existing AWX
(or AAP) installation into Forail.

Connects to the source AWX REST API and recreates Organizations, Users, Teams,
Credential Types, Credentials, Projects, Inventories (groups + hosts), Inventory
Sources, Job Templates, Workflow Job Templates (with their node graph),
Notification Templates, Schedules and RBAC role assignments in this Forail
instance. It is idempotent: re-running matches existing objects by natural key
(name within organization, username for users) and updates them instead of
creating duplicates.

Secrets caveat: the AWX API never returns secret credential inputs (it replaces
them with the literal ``$encrypted$``). This importer brings over the credential
*structure* and any non-secret inputs, but secret values (passwords, SSH keys,
tokens) MUST be re-entered afterwards. The same applies to secret fields inside
notification configurations (tokens, passwords). The command reports how many
such fields need attention.

Group hierarchy and host/group membership ARE imported. Job/Workflow execution
history and ephemeral run state are intentionally NOT imported — this migrates
configuration, not job results.

Example:
    forail-manage import_from_awx \\
        --url https://awx.example.com --token $AWX_TOKEN --dry-run
"""

import json
import logging

import requests

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.contrib.auth.models import User

from forail.main.models.organization import Organization, Team
from forail.main.models.credential import Credential, CredentialType
from forail.main.models.projects import Project
from forail.main.models.inventory import Inventory, Host, Group, InventorySource
from forail.main.models.jobs import JobTemplate
from forail.main.models.workflow import WorkflowJobTemplate, WorkflowJobTemplateNode
from forail.main.models.notifications import NotificationTemplate
from forail.main.models.schedules import Schedule
from forail.main.signals import disable_activity_stream

logger = logging.getLogger('forail.main.commands.import_from_awx')


class AWXClient:
    """Minimal paginated client for the AWX v2 REST API."""

    def __init__(self, base_url, token=None, username=None, password=None, verify=True, timeout=30):
        self.base_url = base_url.rstrip('/')
        self.verify = verify
        self.timeout = timeout
        self.session = requests.Session()
        if token:
            self.session.headers['Authorization'] = 'Bearer %s' % token
        elif username:
            self.session.auth = (username, password or '')
        self.session.headers['Content-Type'] = 'application/json'

    def get_list(self, resource):
        """Yield every result object across all pages of /api/v2/<resource>/."""
        url = '%s/api/v2/%s/' % (self.base_url, resource.strip('/'))
        while url:
            resp = self.session.get(url, verify=self.verify, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            for obj in data.get('results', []):
                yield obj
            nxt = data.get('next')
            url = ('%s%s' % (self.base_url, nxt)) if nxt and nxt.startswith('/') else nxt

    def get_sub_list(self, resource, obj_id, sub):
        """Yield results from a related sub-endpoint, e.g. groups/<id>/hosts/."""
        yield from self.get_list('%s/%s/%s' % (resource.strip('/'), obj_id, sub))


class ImportContext:
    """Carries the awx_id -> forail object maps and run-wide counters."""

    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.maps = {k: {} for k in (
            'organization', 'user', 'team', 'credential_type', 'credential',
            'project', 'inventory', 'group', 'host', 'inventory_source',
            'job_template', 'workflow_job_template', 'workflow_node',
            'notification_template', 'schedule')}
        self.created = {}
        self.updated = {}
        self.secret_fields_pending = 0
        self.role_grants = 0
        self.warnings = []

    def record(self, kind, created):
        d = self.created if created else self.updated
        d[kind] = d.get(kind, 0) + 1

    def warn(self, msg):
        self.warnings.append(msg)
        logger.warning(msg)


# Resources whose import order matters (dependencies first).
RESOURCE_ORDER = [
    'organizations', 'users', 'teams', 'credential_types', 'credentials',
    'projects', 'inventories', 'groups', 'hosts', 'inventory_sources',
    'job_templates', 'workflow_job_templates', 'workflow_nodes',
    'notification_templates', 'schedules', 'roles',
]


class Command(BaseCommand):
    help = ('Import organizations, users, teams, credentials, projects, inventories, '
            'inventory sources, job templates, workflow job templates, notification '
            'templates, schedules and RBAC role assignments from an existing AWX installation.')

    def add_arguments(self, parser):
        parser.add_argument('--url', required=True, help='Base URL of the source AWX install, e.g. https://awx.example.com')
        parser.add_argument('--token', help='OAuth2 token for the source AWX API (preferred).')
        parser.add_argument('--username', help='Username for basic auth (if no token).')
        parser.add_argument('--password', help='Password for basic auth (if no token).')
        parser.add_argument('--insecure', action='store_true', help='Do not verify the source TLS certificate.')
        parser.add_argument('--dry-run', action='store_true', help='Fetch and report what would change, then roll back without writing.')
        parser.add_argument('--resource', action='append', choices=RESOURCE_ORDER,
                            help='Limit to specific resource type(s); may be repeated. Default: all.')

    def handle(self, *args, **options):
        if not options.get('token') and not options.get('username'):
            raise CommandError('Provide --token, or --username/--password.')

        client = AWXClient(
            options['url'],
            token=options.get('token'),
            username=options.get('username'),
            password=options.get('password'),
            verify=not options.get('insecure'),
        )
        # Fail fast on connectivity / auth before opening a transaction.
        try:
            ping = client.session.get('%s/api/v2/ping/' % client.base_url, verify=client.verify, timeout=client.timeout)
            ping.raise_for_status()
        except requests.RequestException as exc:
            raise CommandError('Cannot reach source AWX API at %s: %s' % (options['url'], exc))

        only = set(options.get('resource') or RESOURCE_ORDER)
        ctx = ImportContext(dry_run=options.get('dry_run', False))

        steps = [
            ('organizations', self._import_organizations),
            ('users', self._import_users),
            ('teams', self._import_teams),
            ('credential_types', self._import_credential_types),
            ('credentials', self._import_credentials),
            ('projects', self._import_projects),
            ('inventories', self._import_inventories),
            ('groups', self._import_groups),
            ('hosts', self._import_hosts),
            ('inventory_sources', self._import_inventory_sources),
            ('job_templates', self._import_job_templates),
            ('workflow_job_templates', self._import_workflow_job_templates),
            ('workflow_nodes', self._import_workflow_nodes),
            ('notification_templates', self._import_notification_templates),
            ('schedules', self._import_schedules),
            ('roles', self._import_roles),
        ]

        try:
            with transaction.atomic(), disable_activity_stream():
                for name, fn in steps:
                    if name not in only:
                        continue
                    self.stdout.write('Importing %s ...' % name)
                    fn(client, ctx)
                if ctx.dry_run:
                    transaction.set_rollback(True)
        except requests.RequestException as exc:
            raise CommandError('AWX API error during import: %s' % exc)

        self._report(ctx)

    # ----- helpers ---------------------------------------------------------

    @staticmethod
    def _vars_to_text(value):
        """AWX returns variables as a string (YAML/JSON) or dict; store as text."""
        if isinstance(value, (dict, list)):
            return json.dumps(value)
        return value or ''

    @staticmethod
    def _strip_secrets(inputs):
        """Drop AWX's '$encrypted$' placeholders; return (clean_inputs, n_secret)."""
        clean, n = {}, 0
        for k, v in (inputs or {}).items():
            if v == '$encrypted$':
                n += 1
                continue
            clean[k] = v
        return clean, n

    def _save(self, ctx, kind, obj, created):
        if not ctx.dry_run:
            obj.save()
        ctx.record(kind, created)
        return obj

    # ----- per-resource importers -----------------------------------------

    def _import_organizations(self, client, ctx):
        for o in client.get_list('organizations'):
            obj, created = Organization.objects.get_or_create(name=o['name'])
            obj.description = o.get('description', '') or ''
            if o.get('max_hosts') is not None:
                obj.max_hosts = o['max_hosts']
            self._save(ctx, 'organization', obj, created)
            ctx.maps['organization'][o['id']] = obj

    def _import_users(self, client, ctx):
        for u in client.get_list('users'):
            obj, created = User.objects.get_or_create(username=u['username'])
            obj.first_name = u.get('first_name', '') or ''
            obj.last_name = u.get('last_name', '') or ''
            obj.email = u.get('email', '') or ''
            obj.is_superuser = bool(u.get('is_superuser'))
            if created:
                obj.set_unusable_password()
                ctx.warn('User "%s" created without a password — set one (passwords are not exported by AWX).' % u['username'])
            self._save(ctx, 'user', obj, created)
            ctx.maps['user'][u['id']] = obj

    def _import_teams(self, client, ctx):
        for t in client.get_list('teams'):
            org = ctx.maps['organization'].get(t.get('organization'))
            if org is None:
                ctx.warn('Skipping team "%s": its organization was not imported.' % t.get('name'))
                continue
            obj, created = Team.objects.get_or_create(name=t['name'], organization=org)
            obj.description = t.get('description', '') or ''
            self._save(ctx, 'team', obj, created)
            ctx.maps['team'][t['id']] = obj

    def _import_credential_types(self, client, ctx):
        for ct in client.get_list('credential_types'):
            # Managed types ship with Forail already; match, don't recreate.
            if ct.get('managed'):
                existing = CredentialType.objects.filter(name=ct['name'], managed=True).first()
                if existing:
                    ctx.maps['credential_type'][ct['id']] = existing
                continue
            obj, created = CredentialType.objects.get_or_create(name=ct['name'], defaults={'kind': ct.get('kind', 'cloud')})
            obj.description = ct.get('description', '') or ''
            obj.kind = ct.get('kind', obj.kind)
            obj.inputs = ct.get('inputs', {}) or {}
            obj.injectors = ct.get('injectors', {}) or {}
            self._save(ctx, 'credential_type', obj, created)
            ctx.maps['credential_type'][ct['id']] = obj

    def _import_credentials(self, client, ctx):
        for c in client.get_list('credentials'):
            ctype = ctx.maps['credential_type'].get(c.get('credential_type'))
            if ctype is None:
                ctx.warn('Skipping credential "%s": its credential type was not imported.' % c.get('name'))
                continue
            org = ctx.maps['organization'].get(c.get('organization'))
            obj, created = Credential.objects.get_or_create(
                name=c['name'], credential_type=ctype, organization=org)
            obj.description = c.get('description', '') or ''
            clean_inputs, n_secret = self._strip_secrets(c.get('inputs', {}))
            obj.inputs = clean_inputs
            if n_secret:
                ctx.secret_fields_pending += n_secret
                ctx.warn('Credential "%s": %d secret field(s) must be re-entered (not exported by AWX).' % (c['name'], n_secret))
            self._save(ctx, 'credential', obj, created)
            ctx.maps['credential'][c['id']] = obj

    def _import_projects(self, client, ctx):
        scm_fields = ('scm_type', 'scm_url', 'scm_branch', 'scm_refspec', 'scm_clean',
                      'scm_delete_on_update', 'scm_track_submodules', 'scm_update_on_launch',
                      'scm_update_cache_timeout', 'allow_override', 'timeout', 'local_path')
        for p in client.get_list('projects'):
            org = ctx.maps['organization'].get(p.get('organization'))
            obj, created = Project.objects.get_or_create(name=p['name'], organization=org)
            obj.description = p.get('description', '') or ''
            for f in scm_fields:
                if p.get(f) is not None:
                    setattr(obj, f, p[f])
            cred = ctx.maps['credential'].get(p.get('credential'))
            if cred is not None:
                obj.credential = cred
            self._save(ctx, 'project', obj, created)
            ctx.maps['project'][p['id']] = obj

    def _import_inventories(self, client, ctx):
        for i in client.get_list('inventories'):
            org = ctx.maps['organization'].get(i.get('organization'))
            if org is None:
                ctx.warn('Skipping inventory "%s": its organization was not imported.' % i.get('name'))
                continue
            obj, created = Inventory.objects.get_or_create(name=i['name'], organization=org)
            obj.description = i.get('description', '') or ''
            obj.variables = self._vars_to_text(i.get('variables'))
            obj.kind = i.get('kind', '') or ''
            obj.host_filter = i.get('host_filter') or None
            self._save(ctx, 'inventory', obj, created)
            ctx.maps['inventory'][i['id']] = obj

    def _import_groups(self, client, ctx):
        for g in client.get_list('groups'):
            inv = ctx.maps['inventory'].get(g.get('inventory'))
            if inv is None:
                continue
            obj, created = Group.objects.get_or_create(name=g['name'], inventory=inv)
            obj.description = g.get('description', '') or ''
            obj.variables = self._vars_to_text(g.get('variables'))
            self._save(ctx, 'group', obj, created)
            ctx.maps['group'][g['id']] = obj
        # Wire parent/child group hierarchy now that all groups exist.
        if not ctx.dry_run:
            for awx_id, obj in ctx.maps['group'].items():
                for child in client.get_sub_list('groups', awx_id, 'children'):
                    child_obj = ctx.maps['group'].get(child['id'])
                    if child_obj is not None:
                        obj.children.add(child_obj)

    def _import_hosts(self, client, ctx):
        for h in client.get_list('hosts'):
            inv = ctx.maps['inventory'].get(h.get('inventory'))
            if inv is None:
                continue
            obj, created = Host.objects.get_or_create(name=h['name'], inventory=inv)
            obj.description = h.get('description', '') or ''
            obj.enabled = bool(h.get('enabled', True))
            obj.instance_id = h.get('instance_id', '') or ''
            obj.variables = self._vars_to_text(h.get('variables'))
            self._save(ctx, 'host', obj, created)
            ctx.maps['host'][h['id']] = obj
            # Attach host to its groups.
            if not ctx.dry_run:
                for grp in client.get_sub_list('hosts', h['id'], 'groups'):
                    grp_obj = ctx.maps['group'].get(grp['id'])
                    if grp_obj is not None:
                        grp_obj.hosts.add(obj)

    def _import_job_templates(self, client, ctx):
        simple_fields = ('playbook', 'scm_branch', 'forks', 'limit', 'verbosity', 'job_tags',
                         'skip_tags', 'start_at_task', 'become_enabled', 'allow_simultaneous',
                         'timeout', 'use_fact_cache', 'survey_enabled', 'diff_mode', 'job_type',
                         'host_config_key', 'job_slice_count', 'force_handlers')
        ask_fields = ('ask_inventory_on_launch', 'ask_limit_on_launch', 'ask_scm_branch_on_launch',
                      'ask_tags_on_launch', 'ask_skip_tags_on_launch', 'ask_variables_on_launch',
                      'ask_diff_mode_on_launch', 'ask_job_type_on_launch', 'ask_verbosity_on_launch',
                      'ask_credential_on_launch', 'ask_execution_environment_on_launch')
        for jt in client.get_list('job_templates'):
            inv = ctx.maps['inventory'].get(jt.get('inventory'))
            proj = ctx.maps['project'].get(jt.get('project'))
            obj, created = JobTemplate.objects.get_or_create(name=jt['name'], defaults={'project': proj})
            obj.description = jt.get('description', '') or ''
            obj.inventory = inv
            obj.project = proj
            for f in simple_fields + ask_fields:
                if jt.get(f) is not None:
                    setattr(obj, f, jt[f])
            obj.extra_vars = self._vars_to_text(jt.get('extra_vars'))
            if jt.get('survey_spec'):
                obj.survey_spec = jt['survey_spec']
            self._save(ctx, 'job_template', obj, created)
            ctx.maps['job_template'][jt['id']] = obj
            # Attach credentials (M2M).
            if not ctx.dry_run:
                for cr in client.get_sub_list('job_templates', jt['id'], 'credentials'):
                    cred_obj = ctx.maps['credential'].get(cr['id'])
                    if cred_obj is not None:
                        obj.credentials.add(cred_obj)

    def _unified_jt(self, ctx, awx_id):
        """Resolve an AWX unified_job_template id to its imported Forail object.

        Job templates, projects, inventory sources and workflow job templates all
        descend from UnifiedJobTemplate (multi-table inheritance), so they share a
        single id space — a schedule's or workflow node's ``unified_job_template``
        id matches exactly one of these maps.
        """
        if awx_id is None:
            return None
        for kind in ('job_template', 'workflow_job_template', 'project', 'inventory_source'):
            obj = ctx.maps[kind].get(awx_id)
            if obj is not None:
                return obj
        return None

    def _import_inventory_sources(self, client, ctx):
        opt_fields = ('source', 'source_path', 'source_vars', 'scm_branch', 'enabled_var',
                      'enabled_value', 'host_filter', 'overwrite', 'overwrite_vars',
                      'timeout', 'verbosity', 'limit')
        for s in client.get_list('inventory_sources'):
            inv = ctx.maps['inventory'].get(s.get('inventory'))
            if inv is None:
                ctx.warn('Skipping inventory source "%s": its inventory was not imported.' % s.get('name'))
                continue
            obj, created = InventorySource.objects.get_or_create(name=s['name'], inventory=inv)
            obj.description = s.get('description', '') or ''
            for f in opt_fields:
                if s.get(f) is not None:
                    setattr(obj, f, s[f])
            source_project = ctx.maps['project'].get(s.get('source_project'))
            if source_project is not None:
                obj.source_project = source_project
            obj.update_on_launch = bool(s.get('update_on_launch', False))
            if s.get('update_cache_timeout') is not None:
                obj.update_cache_timeout = s['update_cache_timeout']
            self._save(ctx, 'inventory_source', obj, created)
            ctx.maps['inventory_source'][s['id']] = obj
            # Attach source credential(s) (M2M).
            if not ctx.dry_run:
                for cr in client.get_sub_list('inventory_sources', s['id'], 'credentials'):
                    cred_obj = ctx.maps['credential'].get(cr['id'])
                    if cred_obj is not None:
                        obj.credentials.add(cred_obj)

    def _import_workflow_job_templates(self, client, ctx):
        simple_fields = ('allow_simultaneous', 'survey_enabled', 'ask_variables_on_launch',
                         'limit', 'scm_branch', 'job_tags', 'skip_tags', 'webhook_service')
        for wf in client.get_list('workflow_job_templates'):
            org = ctx.maps['organization'].get(wf.get('organization'))
            obj, created = WorkflowJobTemplate.objects.get_or_create(
                name=wf['name'], organization=org)
            obj.description = wf.get('description', '') or ''
            obj.extra_vars = self._vars_to_text(wf.get('extra_vars'))
            for f in simple_fields:
                if wf.get(f) is not None:
                    setattr(obj, f, wf[f])
            inv = ctx.maps['inventory'].get(wf.get('inventory'))
            if inv is not None:
                obj.inventory = inv
            if wf.get('survey_spec'):
                obj.survey_spec = wf['survey_spec']
            self._save(ctx, 'workflow_job_template', obj, created)
            ctx.maps['workflow_job_template'][wf['id']] = obj

    def _import_workflow_nodes(self, client, ctx):
        """Create workflow nodes, then wire their success/failure/always edges.

        Two passes are required because edges reference sibling nodes that may not
        exist yet on the first pass.
        """
        for node in client.get_list('workflow_job_template_nodes'):
            wfjt = ctx.maps['workflow_job_template'].get(node.get('workflow_job_template'))
            if wfjt is None:
                continue
            ujt = self._unified_jt(ctx, node.get('unified_job_template'))
            identifier = node.get('identifier') or str(node['id'])
            obj, created = WorkflowJobTemplateNode.objects.get_or_create(
                workflow_job_template=wfjt, identifier=identifier)
            obj.unified_job_template = ujt
            obj.all_parents_must_converge = bool(node.get('all_parents_must_converge', False))
            obj.extra_data = node.get('extra_data', {}) or {}
            inv = ctx.maps['inventory'].get(node.get('inventory'))
            if inv is not None:
                obj.inventory = inv
            self._save(ctx, 'workflow_node', obj, created)
            ctx.maps['workflow_node'][node['id']] = obj
        # Second pass: wire the DAG edges now that every node exists.
        if ctx.dry_run:
            return
        for awx_id, obj in ctx.maps['workflow_node'].items():
            for edge in ('success_nodes', 'failure_nodes', 'always_nodes'):
                for child in client.get_sub_list('workflow_job_template_nodes', awx_id, edge):
                    child_obj = ctx.maps['workflow_node'].get(child['id'])
                    if child_obj is not None:
                        getattr(obj, edge).add(child_obj)

    def _import_notification_templates(self, client, ctx):
        for nt in client.get_list('notification_templates'):
            org = ctx.maps['organization'].get(nt.get('organization'))
            if org is None:
                ctx.warn('Skipping notification template "%s": its organization was not imported.' % nt.get('name'))
                continue
            obj, created = NotificationTemplate.objects.get_or_create(name=nt['name'], organization=org)
            obj.description = nt.get('description', '') or ''
            obj.notification_type = nt.get('notification_type') or obj.notification_type
            clean_config, n_secret = self._strip_secrets(nt.get('notification_configuration', {}))
            obj.notification_configuration = clean_config
            if nt.get('messages'):
                obj.messages = nt['messages']
            if n_secret:
                ctx.secret_fields_pending += n_secret
                ctx.warn('Notification template "%s": %d secret field(s) must be re-entered (not exported by AWX).' % (nt['name'], n_secret))
            self._save(ctx, 'notification_template', obj, created)
            ctx.maps['notification_template'][nt['id']] = obj
        # Wire each unified job template's started/success/error notification hooks.
        if ctx.dry_run:
            return
        hooks = (('notification_templates_started', 'notification_templates_started'),
                 ('notification_templates_success', 'notification_templates_success'),
                 ('notification_templates_error', 'notification_templates_error'))
        targets = (('job_templates', 'job_template'),
                   ('workflow_job_templates', 'workflow_job_template'),
                   ('projects', 'project'),
                   ('inventory_sources', 'inventory_source'))
        for endpoint, kind in targets:
            for awx_id, obj in ctx.maps[kind].items():
                for sub, field in hooks:
                    for n in client.get_sub_list(endpoint, awx_id, sub):
                        nt_obj = ctx.maps['notification_template'].get(n['id'])
                        if nt_obj is not None:
                            getattr(obj, field).add(nt_obj)

    def _import_schedules(self, client, ctx):
        for sc in client.get_list('schedules'):
            ujt = self._unified_jt(ctx, sc.get('unified_job_template'))
            if ujt is None:
                ctx.warn('Skipping schedule "%s": its job template was not imported.' % sc.get('name'))
                continue
            if not sc.get('rrule'):
                ctx.warn('Skipping schedule "%s": no rrule.' % sc.get('name'))
                continue
            obj, created = Schedule.objects.get_or_create(
                unified_job_template=ujt, name=sc['name'],
                defaults={'rrule': sc['rrule']})
            obj.description = sc.get('description', '') or ''
            obj.rrule = sc['rrule']
            obj.enabled = bool(sc.get('enabled', True))
            obj.extra_data = sc.get('extra_data', {}) or {}
            self._save(ctx, 'schedule', obj, created)
            ctx.maps['schedule'][sc['id']] = obj

    # Maps the AWX role resource_type (summary_fields.resource_type) to the
    # ctx.maps key holding the imported Forail object for that resource.
    _ROLE_RESOURCE_MAP = {
        'organization': 'organization',
        'team': 'team',
        'inventory': 'inventory',
        'credential': 'credential',
        'project': 'project',
        'job_template': 'job_template',
        'workflow_job_template': 'workflow_job_template',
        'inventory_source': 'inventory_source',
        'notification_template': 'notification_template',
        'credential_type': 'credential_type',
    }

    def _import_roles(self, client, ctx):
        """Recreate RBAC role assignments (which users/teams hold which roles).

        Singleton roles (system administrator/auditor) are applied directly to the
        user; object roles are looked up by ``role_field`` on the imported object.
        Granting a role to a user is ``role.members.add(user)``; granting it to a
        team is ``role.parents.add(team.member_role)`` so the team inherits it.
        """
        for r in client.get_list('roles'):
            role_field = r.get('role_field')
            summary = r.get('summary_fields', {}) or {}
            resource_type = summary.get('resource_type')
            resource_id = summary.get('resource_id')

            target_role = None
            if resource_type is None:
                # Singleton system role (e.g. system_administrator/system_auditor).
                for u in client.get_sub_list('roles', r['id'], 'users'):
                    user = ctx.maps['user'].get(u['id'])
                    if user is None:
                        continue
                    if role_field == 'system_administrator':
                        user.is_superuser = True
                    elif role_field == 'system_auditor':
                        user.is_system_auditor = True
                    else:
                        continue
                    if not ctx.dry_run:
                        user.save()
                    ctx.role_grants += 1
                continue

            map_key = self._ROLE_RESOURCE_MAP.get(resource_type)
            obj = ctx.maps[map_key].get(resource_id) if map_key else None
            if obj is None or not role_field:
                continue
            target_role = getattr(obj, role_field, None)
            if target_role is None:
                continue

            for u in client.get_sub_list('roles', r['id'], 'users'):
                user = ctx.maps['user'].get(u['id'])
                if user is not None:
                    if not ctx.dry_run:
                        target_role.members.add(user)
                    ctx.role_grants += 1
            for t in client.get_sub_list('roles', r['id'], 'teams'):
                team = ctx.maps['team'].get(t['id'])
                if team is not None:
                    if not ctx.dry_run:
                        target_role.parents.add(team.member_role)
                    ctx.role_grants += 1

    # ----- reporting -------------------------------------------------------

    def _report(self, ctx):
        mode = 'DRY RUN (no changes written)' if ctx.dry_run else 'Import complete'
        self.stdout.write('')
        self.stdout.write('=== %s ===' % mode)
        for kind in ('organization', 'user', 'team', 'credential_type', 'credential',
                     'project', 'inventory', 'group', 'host', 'inventory_source',
                     'job_template', 'workflow_job_template', 'workflow_node',
                     'notification_template', 'schedule'):
            c, u = ctx.created.get(kind, 0), ctx.updated.get(kind, 0)
            if c or u:
                self.stdout.write('  %-22s created=%d updated=%d' % (kind, c, u))
        if ctx.role_grants:
            self.stdout.write('  %-22s granted=%d' % ('role_assignments', ctx.role_grants))
        if ctx.secret_fields_pending:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                'ACTION REQUIRED: %d secret credential field(s) were NOT migrated '
                '(AWX does not export secrets). Re-enter them in Forail.' % ctx.secret_fields_pending))
        if ctx.warnings:
            self.stdout.write('  (%d warning(s) — see log for details)' % len(ctx.warnings))
