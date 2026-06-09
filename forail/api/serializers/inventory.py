# Copyright (c) 2015 Ansible, Inc.
# Copyright (c) 2026 Krstan Vjestica / Forail Project
# All Rights Reserved.

"""Inventory serializers for the Forail API."""

import json
import re

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils.encoding import force_str
from django.utils.timezone import now
from rest_framework.exceptions import PermissionDenied
from rest_framework import serializers

from forail.main.models import (
    ActivityStream,
    Credential,
    Group,
    Host,
    Inventory,
    InventorySource,
    InventoryUpdate,
)
from forail.main.utils import (
    has_model_field_prefetched,
    getattrd,
    parse_yaml_or_json,
    get_licenser,
)
from forail.main.utils.filters import SmartFilter
from forail.main.validators import vars_validate_or_raise
from forail.main.signals import update_inventory_computed_fields
from forail.api.versioning import reverse
from forail.api.fields import DeprecatedCredentialField
from forail.api.serializers.base import (
    BaseSerializer,
    BaseSerializerWithVariables,
    LabelsListMixin,
    SUMMARIZABLE_FK_FIELDS,
    CONSTRUCTED_INVENTORY_SOURCE_EDITABLE_FIELDS,
    logger,
)
from forail.api.serializers.unified import (
    UnifiedJobTemplateSerializer,
    UnifiedJobSerializer,
    UnifiedJobListSerializer,
)


class InventorySerializer(LabelsListMixin, BaseSerializerWithVariables):
    show_capabilities = ['edit', 'delete', 'adhoc', 'copy']
    capabilities_prefetch = ['admin', 'adhoc', {'copy': 'organization.inventory_admin'}]

    class Meta:
        model = Inventory
        fields = (
            '*',
            'organization',
            'kind',
            'host_filter',
            'variables',
            'has_active_failures',
            'total_hosts',
            'hosts_with_active_failures',
            'total_groups',
            'has_inventory_sources',
            'total_inventory_sources',
            'inventory_sources_with_failures',
            'pending_deletion',
            'prevent_instance_group_fallback',
        )

    def get_related(self, obj):
        res = super(InventorySerializer, self).get_related(obj)
        res.update(
            dict(
                hosts=self.reverse('api:inventory_hosts_list', kwargs={'pk': obj.pk}),
                variable_data=self.reverse('api:inventory_variable_data', kwargs={'pk': obj.pk}),
                script=self.reverse('api:inventory_script_view', kwargs={'pk': obj.pk}),
                activity_stream=self.reverse('api:inventory_activity_stream_list', kwargs={'pk': obj.pk}),
                job_templates=self.reverse('api:inventory_job_template_list', kwargs={'pk': obj.pk}),
                ad_hoc_commands=self.reverse('api:inventory_ad_hoc_commands_list', kwargs={'pk': obj.pk}),
                access_list=self.reverse('api:inventory_access_list', kwargs={'pk': obj.pk}),
                object_roles=self.reverse('api:inventory_object_roles_list', kwargs={'pk': obj.pk}),
                instance_groups=self.reverse('api:inventory_instance_groups_list', kwargs={'pk': obj.pk}),
                copy=self.reverse('api:inventory_copy', kwargs={'pk': obj.pk}),
                labels=self.reverse('api:inventory_label_list', kwargs={'pk': obj.pk}),
            )
        )
        if obj.kind in ('', 'constructed'):
            res['groups'] = self.reverse('api:inventory_groups_list', kwargs={'pk': obj.pk})
            res['root_groups'] = self.reverse('api:inventory_root_groups_list', kwargs={'pk': obj.pk})
            res['update_inventory_sources'] = self.reverse('api:inventory_inventory_sources_update', kwargs={'pk': obj.pk})
            res['inventory_sources'] = self.reverse('api:inventory_inventory_sources_list', kwargs={'pk': obj.pk})
            res['tree'] = self.reverse('api:inventory_tree_view', kwargs={'pk': obj.pk})
        if obj.organization:
            res['organization'] = self.reverse('api:organization_detail', kwargs={'pk': obj.organization.pk})
        if obj.kind == 'constructed':
            res['input_inventories'] = self.reverse('api:inventory_input_inventories', kwargs={'pk': obj.pk})
            res['constructed_url'] = self.reverse('api:constructed_inventory_detail', kwargs={'pk': obj.pk})
        return res

    def to_representation(self, obj):
        ret = super(InventorySerializer, self).to_representation(obj)
        if obj is not None and 'organization' in ret and not obj.organization:
            ret['organization'] = None
        return ret

    def validate_host_filter(self, host_filter):
        if host_filter:
            try:
                for match in models.JSONField.get_lookups().keys():
                    if match == 'exact':
                        continue
                    match = '__{}'.format(match)
                    if re.match('ansible_facts[^=]+{}='.format(match), host_filter):
                        raise models.base.ValidationError({'host_filter': 'ansible_facts does not support searching with {}'.format(match)})
                SmartFilter().query_from_string(host_filter)
            except RuntimeError as e:
                raise models.base.ValidationError(str(e))
        return host_filter

    def validate(self, attrs):
        kind = None
        if 'kind' in attrs:
            kind = attrs['kind']
        elif self.instance:
            kind = self.instance.kind

        host_filter = None
        if 'host_filter' in attrs:
            host_filter = attrs['host_filter']
        elif self.instance:
            host_filter = self.instance.host_filter

        if kind == 'smart' and not host_filter:
            raise serializers.ValidationError({'host_filter': _('Smart inventories must specify host_filter')})
        return super(InventorySerializer, self).validate(attrs)


class ConstructedFieldMixin(serializers.Field):
    def get_attribute(self, instance):
        if not hasattr(instance, '_constructed_inv_src'):
            instance._constructed_inv_src = instance.inventory_sources.first()
        inv_src = instance._constructed_inv_src
        return super().get_attribute(inv_src)


class ConstructedCharField(ConstructedFieldMixin, serializers.CharField):
    pass


class ConstructedIntegerField(ConstructedFieldMixin, serializers.IntegerField):
    pass


class ConstructedInventorySerializer(InventorySerializer):
    source_vars = ConstructedCharField(
        required=False,
        default=None,
        allow_blank=True,
        help_text=_('The source_vars for the related auto-created inventory source, special to constructed inventory.'),
    )
    update_cache_timeout = ConstructedIntegerField(
        required=False,
        allow_null=True,
        min_value=0,
        default=None,
        help_text=_('The cache timeout for the related auto-created inventory source, special to constructed inventory'),
    )
    limit = ConstructedCharField(
        required=False,
        default=None,
        allow_blank=True,
        help_text=_('The limit to restrict the returned hosts for the related auto-created inventory source, special to constructed inventory.'),
    )
    verbosity = ConstructedIntegerField(
        required=False,
        allow_null=True,
        min_value=0,
        max_value=2,
        default=None,
        help_text=_('The verbosity level for the related auto-created inventory source, special to constructed inventory'),
    )

    class Meta:
        model = Inventory
        fields = ('*', '-host_filter') + CONSTRUCTED_INVENTORY_SOURCE_EDITABLE_FIELDS
        read_only_fields = ('*', 'kind')

    def pop_inv_src_data(self, data):
        inv_src_data = {}
        for field in CONSTRUCTED_INVENTORY_SOURCE_EDITABLE_FIELDS:
            if field in data:
                value = data.pop(field)
                if value is not None:
                    inv_src_data[field] = value
        return inv_src_data

    def apply_inv_src_data(self, inventory, inv_src_data):
        if inv_src_data:
            update_fields = []
            inv_src = inventory.inventory_sources.first()
            for field, value in inv_src_data.items():
                setattr(inv_src, field, value)
                update_fields.append(field)
            if update_fields:
                inv_src.save(update_fields=update_fields)

    def create(self, validated_data):
        validated_data['kind'] = 'constructed'
        inv_src_data = self.pop_inv_src_data(validated_data)
        inventory = super().create(validated_data)
        self.apply_inv_src_data(inventory, inv_src_data)
        return inventory

    def update(self, obj, validated_data):
        inv_src_data = self.pop_inv_src_data(validated_data)
        obj = super().update(obj, validated_data)
        self.apply_inv_src_data(obj, inv_src_data)
        return obj


class InventoryScriptSerializer(InventorySerializer):
    class Meta:
        fields = ()


class HostSerializer(BaseSerializerWithVariables):
    show_capabilities = ['edit', 'delete']
    capabilities_prefetch = ['inventory.admin']

    has_active_failures = serializers.SerializerMethodField()
    has_inventory_sources = serializers.SerializerMethodField()

    class Meta:
        model = Host
        fields = (
            '*',
            'inventory',
            'enabled',
            'instance_id',
            'variables',
            'has_active_failures',
            'has_inventory_sources',
            'last_job',
            'last_job_host_summary',
            'ansible_facts_modified',
        )
        read_only_fields = ('last_job', 'last_job_host_summary', 'ansible_facts_modified')

    def build_relational_field(self, field_name, relation_info):
        field_class, field_kwargs = super(HostSerializer, self).build_relational_field(field_name, relation_info)
        if self.instance and field_name == 'inventory':
            field_kwargs['read_only'] = True
            field_kwargs.pop('queryset', None)
        return field_class, field_kwargs

    def get_related(self, obj):
        res = super(HostSerializer, self).get_related(obj)
        res.update(
            dict(
                variable_data=self.reverse('api:host_variable_data', kwargs={'pk': obj.pk}),
                groups=self.reverse('api:host_groups_list', kwargs={'pk': obj.pk}),
                all_groups=self.reverse('api:host_all_groups_list', kwargs={'pk': obj.pk}),
                job_events=self.reverse('api:host_job_events_list', kwargs={'pk': obj.pk}),
                job_host_summaries=self.reverse('api:host_job_host_summaries_list', kwargs={'pk': obj.pk}),
                activity_stream=self.reverse('api:host_activity_stream_list', kwargs={'pk': obj.pk}),
                inventory_sources=self.reverse('api:host_inventory_sources_list', kwargs={'pk': obj.pk}),
                smart_inventories=self.reverse('api:host_smart_inventories_list', kwargs={'pk': obj.pk}),
                ad_hoc_commands=self.reverse('api:host_ad_hoc_commands_list', kwargs={'pk': obj.pk}),
                ad_hoc_command_events=self.reverse('api:host_ad_hoc_command_events_list', kwargs={'pk': obj.pk}),
                ansible_facts=self.reverse('api:host_ansible_facts_detail', kwargs={'pk': obj.pk}),
            )
        )
        if obj.inventory.kind == 'constructed':
            res['original_host'] = self.reverse('api:host_detail', kwargs={'pk': obj.instance_id})
            res['ansible_facts'] = self.reverse('api:host_ansible_facts_detail', kwargs={'pk': obj.instance_id})
        if obj.inventory:
            res['inventory'] = self.reverse('api:inventory_detail', kwargs={'pk': obj.inventory.pk})
        if obj.last_job:
            res['last_job'] = self.reverse('api:job_detail', kwargs={'pk': obj.last_job.pk})
        if obj.last_job_host_summary:
            res['last_job_host_summary'] = self.reverse('api:job_host_summary_detail', kwargs={'pk': obj.last_job_host_summary.pk})
        return res

    def get_summary_fields(self, obj):
        d = super(HostSerializer, self).get_summary_fields(obj)
        try:
            d['last_job']['job_template_id'] = obj.last_job.job_template.id
            d['last_job']['job_template_name'] = obj.last_job.job_template.name
        except (KeyError, AttributeError):
            pass
        if has_model_field_prefetched(obj, 'groups'):
            group_list = sorted([{'id': g.id, 'name': g.name} for g in obj.groups.all()], key=lambda x: x['id'])[:5]
        else:
            group_list = [{'id': g.id, 'name': g.name} for g in obj.groups.all().order_by('id')[:5]]
        group_cnt = obj.groups.count()
        d.setdefault('groups', {'count': group_cnt, 'results': group_list})
        if obj.inventory.kind == 'constructed':
            summaries_qs = obj.constructed_host_summaries
        else:
            summaries_qs = obj.job_host_summaries
        d.setdefault(
            'recent_jobs',
            [
                {
                    'id': j.job.id,
                    'name': j.job.job_template.name if j.job.job_template is not None else "",
                    'type': j.job.job_type_name,
                    'status': j.job.status,
                    'finished': j.job.finished,
                }
                for j in summaries_qs.select_related('job__job_template').order_by('-created').defer('job__extra_vars', 'job__artifacts')[:5]
            ],
        )
        return d

    def _get_host_port_from_name(self, name):
        port = None
        if name.count(':') == 1:
            name, port = name.split(':')
            try:
                port = int(port)
                if port < 1 or port > 65535:
                    raise ValueError
            except ValueError:
                raise serializers.ValidationError(_(u'Invalid port specification: %s') % force_str(port))
        return name, port

    def validate_name(self, value):
        name = force_str(value or '')
        host, port = self._get_host_port_from_name(name)
        return value

    def validate_inventory(self, value):
        if value.kind in ('constructed', 'smart'):
            raise serializers.ValidationError({"detail": _("Cannot create Host for Smart or Constructed Inventories")})
        return value

    def validate_variables(self, value):
        return vars_validate_or_raise(value)

    def validate(self, attrs):
        name = force_str(attrs.get('name', self.instance and self.instance.name or ''))
        inventory = attrs.get('inventory', self.instance and self.instance.inventory or '')
        host, port = self._get_host_port_from_name(name)

        if port:
            attrs['name'] = host
            variables = force_str(attrs.get('variables', self.instance and self.instance.variables or ''))
            vars_dict = parse_yaml_or_json(variables)
            vars_dict['ansible_ssh_port'] = port
            attrs['variables'] = json.dumps(vars_dict)
        if inventory and Group.objects.filter(name=name, inventory=inventory).exists():
            raise serializers.ValidationError(_('A Group with that name already exists.'))

        return super(HostSerializer, self).validate(attrs)

    def to_representation(self, obj):
        ret = super(HostSerializer, self).to_representation(obj)
        if not obj:
            return ret
        if 'inventory' in ret and not obj.inventory:
            ret['inventory'] = None
        if 'last_job' in ret and not obj.last_job:
            ret['last_job'] = None
        if 'last_job_host_summary' in ret and not obj.last_job_host_summary:
            ret['last_job_host_summary'] = None
        return ret

    def get_has_active_failures(self, obj):
        return bool(obj.last_job_host_summary and obj.last_job_host_summary.failed)

    def get_has_inventory_sources(self, obj):
        return obj.inventory_sources.exists()


class AnsibleFactsSerializer(BaseSerializer):
    class Meta:
        model = Host

    def to_representation(self, obj):
        return obj.ansible_facts


class GroupSerializer(BaseSerializerWithVariables):
    show_capabilities = ['copy', 'edit', 'delete']
    capabilities_prefetch = ['inventory.admin', 'inventory.adhoc']

    class Meta:
        model = Group
        fields = ('*', 'inventory', 'variables')

    def build_relational_field(self, field_name, relation_info):
        field_class, field_kwargs = super(GroupSerializer, self).build_relational_field(field_name, relation_info)
        if self.instance and field_name == 'inventory':
            field_kwargs['read_only'] = True
            field_kwargs.pop('queryset', None)
        return field_class, field_kwargs

    def get_related(self, obj):
        res = super(GroupSerializer, self).get_related(obj)
        res.update(
            dict(
                variable_data=self.reverse('api:group_variable_data', kwargs={'pk': obj.pk}),
                hosts=self.reverse('api:group_hosts_list', kwargs={'pk': obj.pk}),
                potential_children=self.reverse('api:group_potential_children_list', kwargs={'pk': obj.pk}),
                children=self.reverse('api:group_children_list', kwargs={'pk': obj.pk}),
                all_hosts=self.reverse('api:group_all_hosts_list', kwargs={'pk': obj.pk}),
                job_events=self.reverse('api:group_job_events_list', kwargs={'pk': obj.pk}),
                job_host_summaries=self.reverse('api:group_job_host_summaries_list', kwargs={'pk': obj.pk}),
                activity_stream=self.reverse('api:group_activity_stream_list', kwargs={'pk': obj.pk}),
                inventory_sources=self.reverse('api:group_inventory_sources_list', kwargs={'pk': obj.pk}),
                ad_hoc_commands=self.reverse('api:group_ad_hoc_commands_list', kwargs={'pk': obj.pk}),
            )
        )
        if obj.inventory:
            res['inventory'] = self.reverse('api:inventory_detail', kwargs={'pk': obj.inventory.pk})
        return res

    def validate(self, attrs):
        name = force_str(attrs.get('name', self.instance and self.instance.name or ''))
        inventory = attrs.get('inventory', self.instance and self.instance.inventory or '')
        if Host.objects.filter(name=name, inventory=inventory).exists():
            raise serializers.ValidationError(_('A Host with that name already exists.'))
        return super(GroupSerializer, self).validate(attrs)

    def validate_name(self, value):
        if value in ('all', '_meta'):
            raise serializers.ValidationError(_('Invalid group name.'))
        return value

    def validate_inventory(self, value):
        if value.kind in ('constructed', 'smart'):
            raise serializers.ValidationError({"detail": _("Cannot create Group for Smart or Constructed Inventories")})
        return value

    def to_representation(self, obj):
        ret = super(GroupSerializer, self).to_representation(obj)
        if obj is not None and 'inventory' in ret and not obj.inventory:
            ret['inventory'] = None
        return ret


class BulkHostSerializer(HostSerializer):
    class Meta:
        model = Host
        fields = (
            'name',
            'enabled',
            'instance_id',
            'description',
            'variables',
        )


class BulkHostCreateSerializer(serializers.Serializer):
    inventory = serializers.PrimaryKeyRelatedField(
        queryset=Inventory.objects.all(), required=True, write_only=True, help_text=_('Primary Key ID of inventory to add hosts to.')
    )
    hosts = serializers.ListField(
        child=BulkHostSerializer(),
        allow_empty=False,
        max_length=100000,
        write_only=True,
        help_text=_('List of hosts to be created, JSON. e.g. [{"name": "example.com"}, {"name": "127.0.0.1"}]'),
    )

    class Meta:
        model = Inventory
        fields = ('inventory', 'hosts')
        read_only_fields = ()

    def raise_if_host_counts_violated(self, attrs):
        validation_info = get_licenser().validate()

        org = attrs['inventory'].organization

        if org:
            org_active_count = Host.objects.org_active_count(org.id)
            new_hosts = [h['name'] for h in attrs['hosts']]
            org_net_new_host_count = len(new_hosts) - Host.objects.filter(inventory__organization=1, name__in=new_hosts).values('name').distinct().count()
            if org.max_hosts > 0 and org_active_count + org_net_new_host_count > org.max_hosts:
                raise PermissionDenied(
                    _(
                        "You have already reached the maximum number of %s hosts"
                        " allowed for your organization. Contact your System Administrator"
                        " for assistance." % org.max_hosts
                    )
                )

        if validation_info.get('license_type', 'UNLICENSED') == 'open':
            return

        sys_free_instances = validation_info.get('free_instances', 0)
        system_net_new_host_count = Host.objects.exclude(name__in=new_hosts).count()

        if system_net_new_host_count > sys_free_instances:
            hard_error = validation_info.get('trial', False) is True or validation_info['instance_count'] == 10
            if hard_error:
                raise PermissionDenied(_("Host count exceeds available instances."))
            logger.warning(_("Number of hosts allowed by license has been exceeded."))

    def validate(self, attrs):
        request = self.context.get('request', None)
        inv = attrs['inventory']
        if inv.kind != '':
            raise serializers.ValidationError(_('Hosts can only be created in manual inventories (not smart or constructed types).'))
        if len(attrs['hosts']) > settings.BULK_HOST_MAX_CREATE:
            raise serializers.ValidationError(_('Number of hosts exceeds system setting BULK_HOST_MAX_CREATE'))
        if request and not request.user.is_superuser:
            if request.user not in inv.admin_role:
                raise serializers.ValidationError(_(f'Inventory with id {inv.id} not found or lack permissions to add hosts.'))
        current_hostnames = set(inv.hosts.values_list('name', flat=True))
        new_names = [host['name'] for host in attrs['hosts']]
        duplicate_new_names = [n for n in new_names if n in current_hostnames or new_names.count(n) > 1]
        if duplicate_new_names:
            raise serializers.ValidationError(_(f'Hostnames must be unique in an inventory. Duplicates found: {duplicate_new_names}'))

        self.raise_if_host_counts_violated(attrs)

        _now = now()
        for host in attrs['hosts']:
            host['created'] = _now
            host['modified'] = _now
            host['inventory'] = inv
        return attrs

    def create(self, validated_data):
        old_total_hosts = validated_data['inventory'].total_hosts
        result = [Host(**attrs) for attrs in validated_data['hosts']]
        try:
            Host.objects.bulk_create(result)
        except Exception as e:
            raise serializers.ValidationError({"detail": _(f"cannot create host, host creation error {e}")})
        new_total_hosts = old_total_hosts + len(result)
        request = self.context.get('request', None)
        changes = {'total_hosts': [old_total_hosts, new_total_hosts]}
        activity_entry = ActivityStream.objects.create(
            operation='update',
            object1='inventory',
            changes=json.dumps(changes),
            actor=request.user,
        )
        activity_entry.inventory.add(validated_data['inventory'])

        update_inventory_computed_fields.delay(validated_data['inventory'].id)
        return_keys = [k for k in BulkHostSerializer().fields.keys()] + ['id']
        return_data = {}
        host_data = []
        for r in result:
            item = {k: getattr(r, k) for k in return_keys}
            if settings.DATABASES and ('sqlite3' not in settings.DATABASES.get('default', {}).get('ENGINE')):
                item['url'] = reverse('api:host_detail', kwargs={'pk': r.id})
            item['inventory'] = reverse('api:inventory_detail', kwargs={'pk': validated_data['inventory'].id})
            host_data.append(item)
        return_data['url'] = reverse('api:inventory_detail', kwargs={'pk': validated_data['inventory'].id})
        return_data['hosts'] = host_data
        return return_data


class BulkHostDeleteSerializer(serializers.Serializer):
    hosts = serializers.ListField(
        allow_empty=False,
        max_length=100000,
        write_only=True,
        help_text=_('List of hosts ids to be deleted, e.g. [105, 130, 131, 200]'),
    )

    class Meta:
        model = Host
        fields = ('hosts',)

    def validate(self, attrs):
        request = self.context.get('request', None)
        max_hosts = settings.BULK_HOST_MAX_DELETE
        if len(attrs['hosts']) > max_hosts:
            raise serializers.ValidationError(
                {
                    "ERROR": 'Number of hosts exceeds system setting BULK_HOST_MAX_DELETE',
                    "BULK_HOST_MAX_DELETE": max_hosts,
                    "Hosts_count": len(attrs['hosts']),
                }
            )

        attrs['host_qs'] = Host.objects.get_queryset().filter(pk__in=attrs['hosts']).only('id', 'inventory_id', 'name')
        attrs['hosts_data'] = attrs['host_qs'].values()

        if len(attrs['host_qs']) == 0:
            error_hosts = {host: "Hosts do not exist or you lack permission to delete it" for host in attrs['hosts']}
            raise serializers.ValidationError({'hosts': error_hosts})

        if len(attrs['host_qs']) < len(attrs['hosts']):
            hosts_exists = [host['id'] for host in attrs['hosts_data']]
            failed_hosts = list(set(attrs['hosts']).difference(hosts_exists))
            error_hosts = {host: "Hosts do not exist or you lack permission to delete it" for host in failed_hosts}
            raise serializers.ValidationError({'hosts': error_hosts})

        inv_list = list(set([host['inventory_id'] for host in attrs['hosts_data']]))

        errors = dict()
        for inv in Inventory.objects.get_queryset().filter(pk__in=inv_list):
            if request and not request.user.is_superuser:
                if request.user not in inv.admin_role:
                    errors[inv.name] = "Lack permissions to delete hosts from this inventory."
        if errors != {}:
            raise PermissionDenied({"inventories": errors})

        errors = dict()
        for inv in Inventory.objects.get_queryset().filter(pk__in=inv_list):
            if inv.kind != '':
                errors[inv.name] = "Hosts can only be deleted from manual inventories."
        if errors != {}:
            raise serializers.ValidationError({"inventories": errors})
        attrs['inventories'] = inv_list
        return attrs

    def delete(self, validated_data):
        result = {"hosts": dict()}
        changes = {'deleted_hosts': dict()}
        for inventory in validated_data['inventories']:
            changes['deleted_hosts'][inventory] = list()

        for host in validated_data['hosts_data']:
            result["hosts"][host["id"]] = f"The host {host['name']} was deleted"
            changes['deleted_hosts'][host["inventory_id"]].append({"host_id": host["id"], "host_name": host["name"]})

        try:
            validated_data['host_qs'].delete()
        except Exception as e:
            raise serializers.ValidationError({"detail": _(f"cannot delete hosts, host deletion error {e}")})

        request = self.context.get('request', None)

        for inventory in validated_data['inventories']:
            activity_entry = ActivityStream.objects.create(
                operation='update',
                object1='inventory',
                changes=json.dumps(changes['deleted_hosts'][inventory]),
                actor=request.user,
            )
            activity_entry.inventory.add(inventory)

        return result


class GroupTreeSerializer(GroupSerializer):
    children = serializers.SerializerMethodField()

    class Meta:
        model = Group
        fields = ('*', 'children')

    def get_children(self, obj):
        if obj is None:
            return {}
        children_qs = obj.children
        children_qs = children_qs.select_related('inventory')
        children_qs = children_qs.prefetch_related('inventory_source')
        return GroupTreeSerializer(children_qs, many=True).data


class BaseVariableDataSerializer(BaseSerializer):
    class Meta:
        fields = ('variables',)

    def to_representation(self, obj):
        if obj is None:
            return {}
        ret = super(BaseVariableDataSerializer, self).to_representation(obj)
        return parse_yaml_or_json(ret.get('variables', '') or '{}')

    def to_internal_value(self, data):
        data = {'variables': json.dumps(data)}
        return super(BaseVariableDataSerializer, self).to_internal_value(data)


class InventoryVariableDataSerializer(BaseVariableDataSerializer):
    class Meta:
        model = Inventory


class HostVariableDataSerializer(BaseVariableDataSerializer):
    class Meta:
        model = Host


class GroupVariableDataSerializer(BaseVariableDataSerializer):
    class Meta:
        model = Group


class InventorySourceOptionsSerializer(BaseSerializer):
    credential = DeprecatedCredentialField(help_text=_('Cloud credential to use for inventory updates.'))

    class Meta:
        fields = (
            '*',
            'source',
            'source_path',
            'source_vars',
            'scm_branch',
            'credential',
            'enabled_var',
            'enabled_value',
            'host_filter',
            'overwrite',
            'overwrite_vars',
            'custom_virtualenv',
            'timeout',
            'verbosity',
            'limit',
        )
        read_only_fields = ('*', 'custom_virtualenv')

    def get_related(self, obj):
        res = super(InventorySourceOptionsSerializer, self).get_related(obj)
        if obj.credential:
            res['credential'] = self.reverse('api:credential_detail', kwargs={'pk': obj.credential})
        return res

    def validate_source_vars(self, value):
        ret = vars_validate_or_raise(value)
        for env_k in parse_yaml_or_json(value):
            if env_k in settings.INV_ENV_VARIABLE_BLOCKED:
                raise serializers.ValidationError(_("`{}` is a prohibited environment variable".format(env_k)))
        return ret

    def get_summary_fields(self, obj):
        summary_fields = super(InventorySourceOptionsSerializer, self).get_summary_fields(obj)
        all_creds = []
        if 'credential' in summary_fields:
            cred = obj.get_cloud_credential()
            if cred:
                summarized_cred = {'id': cred.id, 'name': cred.name, 'description': cred.description, 'kind': cred.kind, 'cloud': True}
                summary_fields['credential'] = summarized_cred
                all_creds.append(summarized_cred)
                summary_fields['credential']['credential_type_id'] = cred.credential_type_id
            else:
                summary_fields.pop('credential')
        summary_fields['credentials'] = all_creds
        return summary_fields


class InventorySourceSerializer(UnifiedJobTemplateSerializer, InventorySourceOptionsSerializer):
    status = serializers.ChoiceField(choices=InventorySource.INVENTORY_SOURCE_STATUS_CHOICES, read_only=True)
    last_update_failed = serializers.BooleanField(read_only=True)
    last_updated = serializers.DateTimeField(read_only=True)
    show_capabilities = ['start', 'schedule', 'edit', 'delete']
    capabilities_prefetch = [{'admin': 'inventory.admin'}, {'start': 'inventory.update'}]

    class Meta:
        model = InventorySource
        fields = ('*', 'name', 'inventory', 'update_on_launch', 'update_cache_timeout', 'source_project') + (
            'last_update_failed',
            'last_updated',
        )
        extra_kwargs = {'inventory': {'required': True}}

    def get_related(self, obj):
        res = super(InventorySourceSerializer, self).get_related(obj)
        res.update(
            dict(
                update=self.reverse('api:inventory_source_update_view', kwargs={'pk': obj.pk}),
                inventory_updates=self.reverse('api:inventory_source_updates_list', kwargs={'pk': obj.pk}),
                schedules=self.reverse('api:inventory_source_schedules_list', kwargs={'pk': obj.pk}),
                activity_stream=self.reverse('api:inventory_source_activity_stream_list', kwargs={'pk': obj.pk}),
                hosts=self.reverse('api:inventory_source_hosts_list', kwargs={'pk': obj.pk}),
                groups=self.reverse('api:inventory_source_groups_list', kwargs={'pk': obj.pk}),
                notification_templates_started=self.reverse('api:inventory_source_notification_templates_started_list', kwargs={'pk': obj.pk}),
                notification_templates_success=self.reverse('api:inventory_source_notification_templates_success_list', kwargs={'pk': obj.pk}),
                notification_templates_error=self.reverse('api:inventory_source_notification_templates_error_list', kwargs={'pk': obj.pk}),
            )
        )
        if obj.inventory:
            res['inventory'] = self.reverse('api:inventory_detail', kwargs={'pk': obj.inventory.pk})
        if obj.source_project_id is not None:
            res['source_project'] = self.reverse('api:project_detail', kwargs={'pk': obj.source_project.pk})
        if obj.current_update:
            res['current_update'] = self.reverse('api:inventory_update_detail', kwargs={'pk': obj.current_update.pk})
        if obj.last_update:
            res['last_update'] = self.reverse('api:inventory_update_detail', kwargs={'pk': obj.last_update.pk})
        else:
            res['credentials'] = self.reverse('api:inventory_source_credentials_list', kwargs={'pk': obj.pk})
        return res

    def build_relational_field(self, field_name, relation_info):
        field_class, field_kwargs = super(InventorySourceSerializer, self).build_relational_field(field_name, relation_info)
        if self.instance and field_name == 'inventory':
            field_kwargs['read_only'] = True
            field_kwargs.pop('queryset', None)
        return field_class, field_kwargs

    def build_field(self, field_name, info, model_class, nested_depth):
        if field_name == 'credential':
            return self.build_standard_field(field_name, self.credential)
        return super(InventorySourceOptionsSerializer, self).build_field(field_name, info, model_class, nested_depth)

    def to_representation(self, obj):
        ret = super(InventorySourceSerializer, self).to_representation(obj)
        if obj is None:
            return ret
        if 'inventory' in ret and not obj.inventory:
            ret['inventory'] = None
        return ret

    def validate_source_project(self, value):
        if value and value.scm_type == '':
            raise serializers.ValidationError(_("Cannot use manual project for SCM-based inventory."))
        return value

    def validate_inventory(self, value):
        if value and value.kind in ('constructed', 'smart'):
            raise serializers.ValidationError({"detail": _("Cannot create Inventory Source for Smart or Constructed Inventories")})
        return value

    def create(self, validated_data):
        deprecated_fields = {}
        if 'credential' in validated_data:
            deprecated_fields['credential'] = validated_data.pop('credential')
        obj = super(InventorySourceSerializer, self).create(validated_data)
        if deprecated_fields:
            self._update_deprecated_fields(deprecated_fields, obj)
        return obj

    def update(self, obj, validated_data):
        deprecated_fields = {}
        if 'credential' in validated_data:
            deprecated_fields['credential'] = validated_data.pop('credential')
        obj = super(InventorySourceSerializer, self).update(obj, validated_data)
        if deprecated_fields:
            self._update_deprecated_fields(deprecated_fields, obj)
        return obj

    def _update_deprecated_fields(self, fields, obj):
        if 'credential' in fields:
            new_cred = fields['credential']
            existing = obj.credentials.all()
            if new_cred not in existing:
                for cred in existing:
                    obj.credentials.remove(cred)
                if new_cred:
                    obj.credentials.add(new_cred)

    def validate(self, attrs):
        deprecated_fields = {}
        if 'credential' in attrs:
            deprecated_fields['credential'] = attrs.pop('credential')

        def get_field_from_model_or_attrs(fd):
            return attrs.get(fd, self.instance and getattr(self.instance, fd) or None)

        if self.instance and self.instance.source == 'constructed':
            allowed_fields = CONSTRUCTED_INVENTORY_SOURCE_EDITABLE_FIELDS
            for field in attrs:
                if attrs[field] != getattr(self.instance, field) and field not in allowed_fields:
                    raise serializers.ValidationError({"error": _("Cannot change field '{}' on a constructed inventory source.").format(field)})
        elif get_field_from_model_or_attrs('source') == 'scm':
            if ('source' in attrs or 'source_project' in attrs) and get_field_from_model_or_attrs('source_project') is None:
                raise serializers.ValidationError({"source_project": _("Project required for scm type sources.")})
        elif get_field_from_model_or_attrs('source') == 'constructed':
            raise serializers.ValidationError({"error": _('constructed not a valid source for inventory')})
        else:
            redundant_scm_fields = list(filter(lambda x: attrs.get(x, None), ['source_project', 'source_path', 'scm_branch']))
            if redundant_scm_fields:
                raise serializers.ValidationError({"detail": _("Cannot set %s if not SCM type." % ' '.join(redundant_scm_fields))})

        project = get_field_from_model_or_attrs('source_project')
        if get_field_from_model_or_attrs('scm_branch') and not project.allow_override:
            raise serializers.ValidationError({'scm_branch': _('Project does not allow overriding branch.')})

        attrs = super(InventorySourceSerializer, self).validate(attrs)

        if 'credential' in deprecated_fields:
            cred = deprecated_fields['credential']
            attrs['credential'] = cred
            if cred is not None:
                cred = Credential.objects.get(pk=cred)
                view = self.context.get('view', None)
                if (not view) or (not view.request) or (view.request.user not in cred.use_role):
                    raise PermissionDenied()
            cred_error = InventorySource.cloud_credential_validation(get_field_from_model_or_attrs('source'), cred)
            if cred_error:
                raise serializers.ValidationError({"credential": cred_error})

        return attrs


class InventorySourceUpdateSerializer(InventorySourceSerializer):
    can_update = serializers.BooleanField(read_only=True)

    class Meta:
        fields = ('can_update',)

    def validate(self, attrs):
        project = self.instance.source_project
        if project:
            failed_reason = project.get_reason_if_failed()
            if failed_reason:
                raise serializers.ValidationError(failed_reason)

        return super(InventorySourceUpdateSerializer, self).validate(attrs)


class InventoryUpdateSerializer(UnifiedJobSerializer, InventorySourceOptionsSerializer):
    custom_virtualenv = serializers.ReadOnlyField()

    class Meta:
        model = InventoryUpdate
        fields = (
            '*',
            'inventory',
            'inventory_source',
            'license_error',
            'org_host_limit_error',
            'source_project_update',
            'custom_virtualenv',
            'instance_group',
            'scm_revision',
        )

    def get_related(self, obj):
        res = super(InventoryUpdateSerializer, self).get_related(obj)
        try:
            res.update(dict(inventory_source=self.reverse('api:inventory_source_detail', kwargs={'pk': obj.inventory_source.pk})))
        except Exception:
            pass
        res.update(
            dict(
                cancel=self.reverse('api:inventory_update_cancel', kwargs={'pk': obj.pk}),
                notifications=self.reverse('api:inventory_update_notifications_list', kwargs={'pk': obj.pk}),
                events=self.reverse('api:inventory_update_events_list', kwargs={'pk': obj.pk}),
            )
        )
        if obj.source_project_update_id:
            res['source_project_update'] = self.reverse('api:project_update_detail', kwargs={'pk': obj.source_project_update.pk})
        if obj.inventory:
            res['inventory'] = self.reverse('api:inventory_detail', kwargs={'pk': obj.inventory.pk})

        res['credentials'] = self.reverse('api:inventory_update_credentials_list', kwargs={'pk': obj.pk})

        return res


class InventoryUpdateDetailSerializer(InventoryUpdateSerializer):
    source_project = serializers.SerializerMethodField(help_text=_('The project used for this job.'), method_name='get_source_project_id')

    class Meta:
        model = InventoryUpdate
        fields = ('*', 'source_project')

    def get_source_project(self, obj):
        return getattrd(obj, 'source_project_update.unified_job_template', None)

    def get_source_project_id(self, obj):
        return getattrd(obj, 'source_project_update.unified_job_template.id', None)

    def get_related(self, obj):
        res = super(InventoryUpdateDetailSerializer, self).get_related(obj)
        source_project_id = self.get_source_project_id(obj)

        if source_project_id:
            res['source_project'] = self.reverse('api:project_detail', kwargs={'pk': source_project_id})
        return res

    def get_summary_fields(self, obj):
        summary_fields = super(InventoryUpdateDetailSerializer, self).get_summary_fields(obj)

        source_project = self.get_source_project(obj)
        if source_project:
            summary_fields['source_project'] = {}
            for field in SUMMARIZABLE_FK_FIELDS['project']:
                value = getattr(source_project, field, None)
                if value is not None:
                    summary_fields['source_project'][field] = value

        cred = obj.credentials.first()
        if cred:
            summary_fields['credential'] = {
                'id': cred.pk,
                'name': cred.name,
                'description': cred.description,
                'kind': cred.kind,
                'cloud': cred.credential_type.kind == 'cloud',
            }

        return summary_fields


class InventoryUpdateListSerializer(InventoryUpdateSerializer, UnifiedJobListSerializer):
    class Meta:
        model = InventoryUpdate


class InventoryUpdateCancelSerializer(InventoryUpdateSerializer):
    can_cancel = serializers.BooleanField(read_only=True)

    class Meta:
        fields = ('can_cancel',)
