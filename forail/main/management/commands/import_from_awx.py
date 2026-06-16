"""
import_from_awx — one-shot migration of configuration from an existing AWX
(or AAP) installation into Forail.

Connects to the source AWX REST API and recreates Organizations, Users, Teams,
Credential Types, Credentials, Projects, Inventories (groups + hosts) and Job
Templates in this Forail instance. It is idempotent: re-running matches existing
objects by natural key (name within organization, username for users) and
updates them instead of creating duplicates.

Secrets caveat: the AWX API never returns secret credential inputs (it replaces
them with the literal ``$encrypted$``). This importer brings over the credential
*structure* and any non-secret inputs, but secret values (passwords, SSH keys,
tokens) MUST be re-entered afterwards. The command reports how many such fields
need attention.

Not yet handled (documented TODO): Workflow Job Templates, Schedules,
Notification Templates, and inventory sources. Group hierarchy and host/group
membership ARE imported.

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
from forail.main.models.inventory import Inventory, Host, Group
from forail.main.models.jobs import JobTemplate
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
            'project', 'inventory', 'group', 'host', 'job_template')}
        self.created = {}
        self.updated = {}
        self.secret_fields_pending = 0
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
    'projects', 'inventories', 'groups', 'hosts', 'job_templates',
]


class Command(BaseCommand):
    help = 'Import organizations, users, teams, credentials, projects, inventories and job templates from an existing AWX installation.'

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
            ('job_templates', self._import_job_templates),
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

    # ----- reporting -------------------------------------------------------

    def _report(self, ctx):
        mode = 'DRY RUN (no changes written)' if ctx.dry_run else 'Import complete'
        self.stdout.write('')
        self.stdout.write('=== %s ===' % mode)
        for kind in ('organization', 'user', 'team', 'credential_type', 'credential',
                     'project', 'inventory', 'group', 'host', 'job_template'):
            c, u = ctx.created.get(kind, 0), ctx.updated.get(kind, 0)
            if c or u:
                self.stdout.write('  %-16s created=%d updated=%d' % (kind, c, u))
        if ctx.secret_fields_pending:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                'ACTION REQUIRED: %d secret credential field(s) were NOT migrated '
                '(AWX does not export secrets). Re-enter them in Forail.' % ctx.secret_fields_pending))
        if ctx.warnings:
            self.stdout.write('  (%d warning(s) — see log for details)' % len(ctx.warnings))
