# !/usr/bin/env python
# encoding: utf-8
"""
:copyright (c) 2014 - 2016, The Regents of the University of California, through Lawrence Berkeley National Laboratory (subject to receipt of any required approvals from the U.S. Department of Energy) and contributors. All rights reserved.  # NOQA
:author

Search methods pertaining to buildings.

"""
import operator
import json
import re
import logging

from django.db.models import Q
from seed.lib.superperms.orgs.models import Organization
from .models import (
    BuildingSnapshot,
    ColumnMapping,
    Property,
    PropertyState,
    PropertyView,
    TaxLot,
    TaxLotState,
    TaxLotView
)
from .utils.mapping import get_mappable_types
from .utils import search as search_utils
from seed.public.models import PUBLIC
from functools import reduce

_log = logging.getLogger(__name__)


# TODO: obsolete?
def get_building_fieldnames():
    """returns a list of field names for the BuildingSnapshot class/model that
    will be searched against
    """
    return [
        'pm_property_id',
        # 'tax_lot_id',
        'address_line_1',
        'property_name',
    ]


# TODO: remove reference to buildingsnapshot
def search_buildings(q, fieldnames=None, queryset=None):
    """returns a queryset for matching buildings
    :param str or unicode q: search string
    :param list fieldnames: list of BuildingSnapshot model fieldnames
        (defaults to those generated by get_building_field_names())
    :param queryset: optional queryset to filter from, defaults to
        BuildingSnapshot.objects.none()
    :returns: :queryset: queryset of matching buildings
    """
    if fieldnames is None:
        fieldnames = get_building_fieldnames()
    if queryset is None:
        queryset = BuildingSnapshot.objects.none()
    if q == '':
        return queryset
    qgroup = reduce(operator.or_, (
        Q(**{fieldname + '__icontains': q}) for fieldname in fieldnames
    ))
    return queryset.filter(qgroup)


def _search(q, fieldnames, queryset):
    """returns a queryset for matching objects
    :param str or unicode q: search string
    :param list fieldnames: list of model fieldnames
    :param queryset: "optional" queryset to filter from, will all return an empty queryset if missing.
    :returns: :queryset: queryset of matching buildings
    """
    if q == '':
        return queryset
    qgroup = reduce(operator.or_, (
        Q(**{fieldname + '__icontains': q}) for fieldname in fieldnames
    ))
    return queryset.filter(qgroup)


def search_properties(q, fieldnames=None, queryset=None):
    if queryset is None:
        return PropertyState.objects.none()
    if fieldnames is None:
        fieldnames = [
            'pm_parent_property_id'
            'jurisdiction_property_id'
            'address_line_1',
            'property_name',
        ]
    return _search(q, fieldnames, queryset)


def search_taxlots(q, fieldnames=None, queryset=None):
    if queryset is None:
        return TaxLotState.objects.none()
    if fieldnames is None:
        fieldnames = [
            'jurisdiction_tax_lot_id',
            'address'
            'block_number'
        ]
    return _search(q, fieldnames, queryset)


def generate_paginated_results(queryset, number_per_page=25, page=1,
                               whitelist_orgs=None, below_threshold=False,
                               matching=True):
    """
    Return a page of results as a list from the queryset for the given fields

    :param queryset: optional queryset to filter from
    :param int number_per_page: optional number of results per page
    :param int page: optional page of results to get
    :param whitelist_orgs: a queryset returning the organizations in which all \
        building fields can be returned, otherwise only the parent \
        organization's ``exportable_fields`` should be returned. The \
        ``whitelist_orgs`` are the orgs the request user belongs.
    :param below_threshold: True if less than the parent org's query threshold \
        is greater than the number of queryset results. If True, only return \
        buildings within whitelist_orgs.
    :param matching: Toggle expanded parent and children data, including
        coparent and confidence

    Usage::

        generate_paginated_results(q, 1)

    Returns::

        [
            {
                'gross_floor_area': 1710,
                'site_eui': 123,
                'tax_lot_id': 'a-tax-lot-id',
                'year_built': 2001
            }
        ]
    """

    # This method seems to be doing way too much work by enforcing the whitelisting
    parent_org = None
    # if whitelist_orgs:
    #     parent_org = whitelist_orgs.first().parent_org

    page = page - 1 if page > 0 else 0  # zero index
    # MAX_RESULTS = 100
    # number_per_page = min(MAX_RESULTS, number_per_page)
    start = page * number_per_page
    end = start + number_per_page
    if isinstance(queryset, list):
        # hack until we can sort json_queryset as a queryset
        building_count = len(queryset)
    else:
        building_count = queryset.count()

    if start > building_count:
        return []

    if end > building_count:
        end = building_count

    building_list = []
    buildings_from_query = queryset[start:end]

    if parent_org:
        exportable_fields = parent_org.exportable_fields
        exportable_field_names = exportable_fields.values_list(
            'name', flat=True
        )
    else:
        exportable_field_names = None

    for b in buildings_from_query:
        # check and process buildings from other orgs
        if is_not_whitelist_building(parent_org, b, whitelist_orgs):
            building_dict = b.to_dict(
                exportable_field_names,
                include_related_data=matching
            )
        else:
            building_dict = b.to_dict(include_related_data=matching)
        # see if a building is matched

        # This data is only needed on mapping/matching steps, not general filtering
        # if matching:
            # co_parent = b.co_parent
            # if co_parent:
            #     building_dict['matched'] = True
            #     building_dict['coparent'] = co_parent.to_dict()
            #     child = b.children.first()
            #     if child:
            #         building_dict['confidence'] = child.confidence
            # else:
            #     building_dict['matched'] = False

        # only add the buildings if it is in an org the user belongs or the
        # query count exceeds the query threshold
        if not below_threshold:  # or not is_not_whitelist_building(parent_org, b, whitelist_orgs)
            building_list.append(building_dict)

    return building_list, building_count


def is_not_whitelist_building(parent_org, building, whitelist_orgs):
    """returns false if a building is part of the whitelist_orgs

    :param parent_org: the umbrella parent Organization instance.
    :param building: the BuildingSnapshot inst.
    :param whitelist_orgs: queryset of Organization instances.
    :returns: bool
    """
    return parent_org and building.super_organization not in whitelist_orgs


def filter_other_params(queryset, other_params, db_columns):
    """applies a dictionary filter to the query set. Does some domain specific parsing, mostly to remove extra
    query params and deal with ranges. Ranges should be passed in as '<field name>__lte' or '<field name>__gte'
    e.g. other_params = {'gross_floor_area__lte': 50000}

    :param Django Queryset queryset: queryset to be filtered
    :param dict other_params: dictionary to be parsed and applied to filter.
    :param dict db_columns: list of column names, extra_data blob outside these
    :returns: Django Queryset:
    """

    # Build query as Q objects so we can AND and OR.
    query_filters = Q()
    for k, v in other_params.iteritems():
        in_columns = search_utils.is_column(k, db_columns)
        if in_columns and k != 'q' and v is not None and v != '' and v != []:
            exact_match = search_utils.is_exact_match(v)
            empty_match = search_utils.is_empty_match(v)
            not_empty_match = search_utils.is_not_empty_match(v)
            case_insensitive_match = search_utils.is_case_insensitive_match(v)
            is_numeric_expression = search_utils.is_numeric_expression(v)
            is_string_expression = search_utils.is_string_expression(v)
            exclude_filter = search_utils.is_exclude_filter(v)
            exact_exclude_filter = search_utils.is_exact_exclude_filter(v)

            if exact_match:
                query_filters &= Q(**{"%s__exact" % k: exact_match.group(2)})
            elif case_insensitive_match:
                query_filters &= Q(**{"%s__iexact" % k: case_insensitive_match.group(2)})
            elif empty_match:
                query_filters &= Q(**{"%s__exact" %
                                      k: ''}) | Q(**{"%s__isnull" %
                                                     k: True})
            elif not_empty_match:
                query_filters &= ~Q(**{"%s__exact" %
                                       k: ''}) & Q(**{"%s__isnull" %
                                                      k: False})
            elif is_numeric_expression:
                parts = search_utils.NUMERIC_EXPRESSION_REGEX.findall(v)
                query_filters &= search_utils.parse_expression(k, parts)
            elif is_string_expression:
                parts = search_utils.STRING_EXPRESSION_REGEX.findall(v)
                query_filters &= search_utils.parse_expression(k, parts)
            elif exclude_filter:
                query_filters &= ~Q(**{"%s__icontains" % k: exclude_filter.group(1)})
            elif exact_exclude_filter:
                query_filters &= ~Q(**{"%s__exact" % k: exact_exclude_filter.group(2)})
            elif ('__lt' in k or
                  '__lte' in k or
                  '__gt' in k or
                  '__gte' in k):

                # Check if this is ISO8601 from a input date. Shorten to YYYY-MM-DD
                if search_utils.is_date_field(k) and re.match(r'^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}.\d{3}\w$', v):
                    v = re.search(r'^\d{4}-\d{2}-\d{2}', v).group()

                query_filters &= Q(**{"%s" % k: v})
            elif ('__isnull' in k or
                  k == 'import_file_id' or k == 'source_type'):
                query_filters &= Q(**{"%s" % k: v})

            elif k == 'canonical_building__labels':
                for l in v:
                    queryset &= queryset.filter(**{
                        'canonical_building__labels': l
                    })
            else:
                query_filters &= Q(**{"%s__icontains" % k: v})

    try:
        queryset = queryset.filter(query_filters)
    except ValueError:
        # Return nothing if invalid queries happen. Most likely
        # this is caused by using operators in the wrong fields.
        queryset = queryset.none()

    # handle extra_data with json_query
    for k, v in other_params.iteritems():
        if (not search_utils.is_column(k, db_columns)) and k != 'q' and v:

            exact_match = search_utils.is_exact_match(v)
            empty_match = search_utils.is_empty_match(v)
            not_empty_match = search_utils.is_not_empty_match(v)
            case_insensitive_match = search_utils.is_case_insensitive_match(v)
            exclude_filter = search_utils.is_exclude_filter(v)
            exact_exclude_filter = search_utils.is_exact_exclude_filter(v)

            if empty_match:
                # Filter for records that DO NOT contain this field OR
                # contain a blank value for this field.
                queryset = queryset.filter(
                    Q(**{'extra_data__at_%s__isnull' % k: True}) |
                    Q(**{'extra_data__at_%s' % k: ''})
                )
            elif not_empty_match:
                # Only return records that have the key in extra_data, but the
                # value is not empty.
                queryset = queryset.filter(
                    Q(**{'extra_data__at_%s__isnull' % k: False}) & ~Q(**{'extra_data__at_%s' % k: ''})
                )
            elif exclude_filter:
                # Exclude this value
                queryset = queryset.filter(
                    ~Q(**{'extra_data__at_%s__icontains' % k: exclude_filter.group(1)})
                )
            elif exact_exclude_filter:
                # Exclude this exact value
                queryset = queryset.filter(
                    ~Q(**{'extra_data__at_%s__exact' % k: exact_exclude_filter.group(2)})
                )
            elif exact_match:
                queryset = queryset.filter(
                    Q(**{'extra_data__at_%s__exact' % k: exact_match.group(2)})
                )
            elif case_insensitive_match:
                queryset = queryset.filter(
                    Q(**{'extra_data__at_%s__iexact' % k: case_insensitive_match.group(2)})
                )
            elif k.endswith(('__gt', '__gte', '__lt', '__lte')):
                queryset = queryset.filter(
                    Q(**{'extra_data__at_%s' % k: v})
                )
            else:
                queryset = queryset.filter(
                    Q(**{'extra_data__at_%s__icontains' % k: v})
                )
    return queryset


def parse_body(request):
    """parses the request body for search params, q, etc

    :param request: django wsgi request object
    :return: dict

    Example::

        {
            'exclude': dict, exclude dict for django queryset
            'order_by': str, query order_by, defaults to 'tax_lot_id'
            'sort_reverse': bool, True if ASC, False if DSC
            'page': int, pagination page
            'number_per_page': int, number per pagination page
            'show_shared_buildings': bool, whether to search across all user's orgs
            'q': str, global search param
            'other_search_params': dict, filter params
            'project_id': str, project id if exists in body
        }
    """
    try:
        body = json.loads(request.body)
    except ValueError:
        body = {}

    return process_search_params(
        params=body,
        user=request.user,
        is_api_request=getattr(request, 'is_api_request', False),
    )


def process_search_params(params, user, is_api_request=False):
    """
    Given a python representation of a search query, process it into the
    internal format that is used for searching, filtering, sorting, and pagination.

    :param params: a python object representing the search query
    :param user: the user this search is for
    :param is_api_request: bool, boolean whether this search is being done as an api request.
    :returns: dict

    Example::

        {
            'exclude': dict, exclude dict for django queryset
            'order_by': str, query order_by, defaults to 'tax_lot_id'
            'sort_reverse': bool, True if ASC, False if DSC
            'page': int, pagination page
            'number_per_page': int, number per pagination page
            'show_shared_buildings': bool, whether to search across all user's orgs
            'q': str, global search param
            'other_search_params': dict, filter params
            'project_id': str, project id if exists in body
        }
    """
    q = params.get('q', '')
    other_search_params = params.get('filter_params', {})
    exclude = other_search_params.pop('exclude', {})
    # inventory_type = params.pop('inventory_type', None)
    order_by = params.get('order_by', 'id')
    sort_reverse = params.get('sort_reverse', False)
    if isinstance(sort_reverse, basestring):
        sort_reverse = sort_reverse == 'true'
    page = int(params.get('page', 1))
    number_per_page = int(params.get('number_per_page', 10))
    if 'show_shared_buildings' in params:
        show_shared_buildings = params.get('show_shared_buildings')
    elif not is_api_request:
        show_shared_buildings = getattr(
            user, 'show_shared_buildings', False
        )
    else:
        show_shared_buildings = False

    return {
        'organization_id': params.get('organization_id'),
        'exclude': exclude,
        'order_by': order_by,
        'sort_reverse': sort_reverse,
        'page': page,
        'number_per_page': number_per_page,
        'show_shared_buildings': show_shared_buildings,
        'q': q,
        'other_search_params': other_search_params,
        'project_id': params.get('project_id')
    }


def build_shared_buildings_orgs(orgs):
    """returns a list of sibling and parent orgs"""
    other_orgs = []
    for org in orgs:
        if org.parent_org:
            # this is a child org, so get all of the other
            # child orgs of this org's parents.
            other_orgs.extend(org.parent_org.child_orgs.all())
            other_orgs.append(org.parent_org)
        else:
            # this is a parent org, so get all of the child orgs
            other_orgs.extend(org.child_orgs.all())
            other_orgs.append(org)
    # remove dups
    other_orgs = list(set(other_orgs))
    return other_orgs


def build_json_params(order_by, sort_reverse):
    """returns db_columns, extra_data_sort, and updated order_by

    :param str order_by: field to order_by
    :returns: tuple: db_columns: dict of known DB columns i.e. non-JsonField,
        extra_data_sort bool if order_by is in ``extra_data`` JsonField,
        order_by str if sort_reverse and DB column prepend a '-' for the django
        order_by
    """
    extra_data_sort = False
    db_columns = get_mappable_types()
    db_columns['project_building_snapshots__status_label__name'] = ''
    db_columns['project__slug'] = ''
    db_columns['canonical_building__labels'] = ''
    db_columns['children'] = ''
    db_columns['parents'] = ''

    if order_by not in db_columns:
        extra_data_sort = True
    if sort_reverse and not extra_data_sort:
        order_by = "-%s" % order_by

    return db_columns, extra_data_sort, order_by


def get_orgs_w_public_fields():
    """returns a list of orgs that have publicly shared fields"""
    return list(Organization.objects.filter(
        sharedbuildingfield__field_type=PUBLIC
    ).distinct())


def search_public_buildings(request, orgs):
    """returns a queryset or list of buildings matching the search params and count

    :param request: wsgi request (Django) for parsing params
    :param orgs: list of Organization instances to search within
    :returns: tuple (search_results_list, result count)
    """
    params = parse_body(request)
    other_search_params = params['other_search_params']
    # add some filters to the dict of known column names so search_buildings
    # doesn't think they are part of extra_data
    db_columns, extra_data_sort, params['order_by'] = build_json_params(
        params['order_by'], params['sort_reverse']
    )

    building_snapshots = create_building_queryset(
        orgs,
        params['exclude'],
        params['order_by'],
        extra_data_sort=extra_data_sort,
    )

    # full text search across a couple common fields
    buildings_queryset = search_buildings(
        params['q'], queryset=building_snapshots
    )
    buildings_queryset = filter_other_params(
        buildings_queryset, other_search_params, db_columns
    )
    if extra_data_sort:
        buildings_queryset = buildings_queryset.json_order_by(
            params['order_by'],
            order_by=params['order_by'],
            order_by_rev=params['sort_reverse'],
        )
    if isinstance(buildings_queryset, list):
        buildings_count = len(buildings_queryset)
    else:
        buildings_count = buildings_queryset.count()

    return buildings_queryset, buildings_count


def create_building_queryset(
        orgs,
        exclude,
        order_by,
        other_orgs=None,
        extra_data_sort=False,
):
    """creates a queryset of buildings within orgs. If ``other_orgs``, buildings
    in both orgs and other_orgs will be represented in the queryset.

    :param orgs: queryset of Organization inst.
    :param exclude: django query exclude dict.
    :param order_by: django query order_by str.
    :param other_orgs: list of other orgs to ``or`` the query
    """
    distinct_order_by = order_by.lstrip('-')

    if other_orgs:
        if extra_data_sort:
            return BuildingSnapshot.objects.filter(
                (
                    Q(super_organization__in=orgs) |
                    Q(super_organization__in=other_orgs)
                ),
                canonicalbuilding__active=True
            ).exclude(**exclude)
        else:
            return BuildingSnapshot.objects.order_by(
                order_by, 'pk'
            ).filter(
                (
                    Q(super_organization__in=orgs) |
                    Q(super_organization__in=other_orgs)
                ),
                canonicalbuilding__active=True
            ).exclude(**exclude).distinct(distinct_order_by, 'pk')
    else:
        if extra_data_sort:
            return BuildingSnapshot.objects.filter(
                super_organization__in=orgs,
                canonicalbuilding__active=True
            ).exclude(**exclude)
        else:
            result = BuildingSnapshot.objects.order_by(
                order_by, 'pk'
            ).filter(
                super_organization__in=orgs,
                canonicalbuilding__active=True
            ).exclude(**exclude).distinct(distinct_order_by, 'pk')

            return result


def remove_results_below_q_threshold(search_results):
    """removes buildings if total count of buildings grouped by org is less
    than their org's public query threshold

    :param list/queryset search_results: search results
    :returns: list or queryset
    """
    manual_group_by = {}
    thresholds = {}
    for b in search_results:
        parent_org = b.super_organization.get_parent()
        if parent_org.id not in manual_group_by:
            manual_group_by[parent_org.id] = 1
            thresholds[parent_org.id] = parent_org.query_threshold
        else:
            manual_group_by[parent_org.id] += 1
    # build list of parent orgs with not enough results
    orgs_below_threshold = []
    for org_id, count in manual_group_by.items():
        if count < thresholds[org_id]:
            orgs_below_threshold.append(org_id)
    # remove buildings from blacklisted parent orgs
    results = []
    for sr in search_results:
        if sr.super_organization.get_parent() not in orgs_below_threshold:
            results.append(sr)
    return results


def paginate_results(request, search_results):
    """returns a paginated list of dict results"""
    params = parse_body(request)
    page = params['page'] - 1 if params['page'] > 0 else 0  # zero index
    MAX_RESULTS = 100
    number_per_page = min(MAX_RESULTS, params['number_per_page'])
    start = page * number_per_page
    end = start + number_per_page
    search_results = search_results[start:end]

    building_list = []
    for b in search_results:
        building_dict = b.to_dict()
        # see if a building is matched
        co_parent = b.co_parent
        if co_parent:
            building_dict['matched'] = True
            building_dict['coparent'] = co_parent.to_dict()
            child = b.children.first()
            if child:
                building_dict['confidence'] = child.confidence
        else:
            building_dict['matched'] = False

        building_list.append(building_dict)
    return building_list


def mask_results(search_results):
    """masks (deletes dict keys) for non-shared public fields"""

    whitelist_fields = {}
    results = []
    for b in search_results:
        parent_org = Organization.objects.get(pk=b['super_organization'])
        parent_org = parent_org.get_parent()
        if parent_org.id not in whitelist_fields:
            whitelist_fields[parent_org.id] = []
            for s in parent_org.sharedbuildingfield_set.filter(
                    field_type=PUBLIC
            ):
                whitelist_fields[parent_org.id].append(s.field.name)

        d = {}
        for key in b:
            if key in whitelist_fields[parent_org.id]:
                d[key] = b[key]
        results.append(d)
    return results


def orchestrate_search_filter_sort(params, user, skip_sort=False):
    """
    Given a parsed set of params, perform the search, filter, and sort for
    BuildingSnapshot's
    """
    other_search_params = params['other_search_params']
    # add some filters to the dict of known column names so search_buildings
    # doesn't think they are part of extra_data
    db_columns, extra_data_sort, params['order_by'] = build_json_params(
        params['order_by'], params['sort_reverse']
    )

    # get all buildings for a user's orgs and sibling orgs
    orgs = user.orgs.all()
    other_orgs = []
    if params['show_shared_buildings']:
        other_orgs = build_shared_buildings_orgs(orgs)

    building_snapshots = create_building_queryset(
        orgs,
        params['exclude'],
        params['order_by'],
        other_orgs=other_orgs,
        extra_data_sort=extra_data_sort,
    )

    # full text search across a couple common fields
    buildings_queryset = search_buildings(
        params['q'], queryset=building_snapshots
    )
    buildings_queryset = filter_other_params(
        buildings_queryset, other_search_params, db_columns
    )

    # sorting
    if extra_data_sort and not skip_sort:
        ed_mapping = ColumnMapping.objects.filter(
            super_organization__in=orgs,
            column_mapped__column_name=params['order_by'],
        ).first()
        ed_column = ed_mapping.column_mapped.filter(
            column_name=params['order_by']
        ).first()
        ed_unit = ed_column.unit

        buildings_queryset = buildings_queryset.json_order_by(
            params['order_by'],
            order_by=params['order_by'],
            order_by_rev=params['sort_reverse'],
            unit=ed_unit,
        )

    return buildings_queryset


def get_inventory_fieldnames(inventory_type):
    """returns a list of field names that will be searched against
    """
    return {
        'property': [
            'address_line_1', 'pm_property_id',
            'jurisdiction_property_identifier'
        ],
        'taxlot': ['jurisdiction_taxlot_id', 'address'],
        'property_view': ['property_id', 'cycle_id', 'state_id'],
        'taxlot_view': ['taxlot_id', 'cycle_id', 'state_id'],
    }[inventory_type]


def search_inventory(inventory_type, q, fieldnames=None, queryset=None):
    """returns a queryset for matching Taxlot(View)/Property(View)
    :param str or unicode q: search string
    :param list fieldnames: list of  model fieldnames
    :param queryset: optional queryset to filter from, defaults to
        BuildingSnapshot.objects.none()
    :returns: :queryset: queryset of matching buildings
    """
    Model = {
        'property': Property, 'property_view': PropertyView,
        'taxlot': TaxLot, 'taxlot_view': TaxLotView,
    }[inventory_type]
    if not fieldnames:
        fieldnames = get_inventory_fieldnames(inventory_type)
    if queryset is None:
        queryset = Model.objects.none()
    if q == '':
        return queryset
    qgroup = reduce(operator.or_, (
        Q(**{fieldname + '__icontains': q}) for fieldname in fieldnames
    ))
    return queryset.filter(qgroup)


def create_inventory_queryset(inventory_type, orgs, exclude, order_by, other_orgs=None):
    """creates a queryset of properties or taxlots within orgs.
    If ``other_orgs``, properties/taxlots in both orgs and other_orgs
    will be represented in the queryset.

    :param inventory_type: property or taxlot.
    :param orgs: queryset of Organization inst.
    :param exclude: django query exclude dict.
    :param order_by: django query order_by str.
    :param other_orgs: list of other orgs to ``or`` the query
    """
    # return immediately if no inventory type
    # i.e. when called by get_serializer in LabelViewSet
    # as there should be no inventory
    if not inventory_type:
        return []
    Model = {
        'property': Property, 'property_view': PropertyView,
        'taxlot': TaxLot, 'taxlot_view': TaxLotView,
    }[inventory_type]

    distinct_order_by = order_by.lstrip('-')

    if inventory_type.endswith('view'):
        filter_key = "{}__organization_id__in".format(
            inventory_type.split('_')[0]
        )
    else:
        filter_key = "organization_id__in"
    orgs_filter_dict = {filter_key: orgs}
    other_orgs_filter_dict = {filter_key: other_orgs}

    if other_orgs:
        return Model.objects.order_by(order_by, 'pk').filter(
            (
                Q(**orgs_filter_dict) | Q(**other_orgs_filter_dict)
            ),
        ).exclude(**exclude).distinct(distinct_order_by, 'pk')
    else:
        result = Model.objects.order_by(order_by, 'pk').filter(
            **orgs_filter_dict
        ).exclude(**exclude).distinct(distinct_order_by, 'pk')

    return result


def inventory_search_filter_sort(inventory_type, params, user):
    """
    Given a parsed set of params, perform the search, filter, and sort for
    Properties or Taxlots
    """
    sort_reverse = params['sort_reverse']
    order_by = params['order_by']
    order_by = "-{}".format(order_by) if sort_reverse else order_by

    # get all buildings for a user's orgs and sibling orgs
    orgs = user.orgs.all().filter(pk=params['organization_id'])
    other_orgs = []
    # this is really show all orgs TODO better param/func name?
    if params['show_shared_buildings']:
        other_orgs = build_shared_buildings_orgs(orgs)

    inventory = create_inventory_queryset(
        inventory_type,
        orgs,
        params['exclude'],
        order_by,
        other_orgs=other_orgs,
    )

    if inventory:
        # full text search across a couple common fields
        inventory = search_inventory(
            inventory_type, params['q'], queryset=inventory
        )

    return inventory
