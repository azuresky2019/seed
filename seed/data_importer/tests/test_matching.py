# !/usr/bin/env python
# encoding: utf-8
"""
:copyright (c) 2014 - 2019, The Regents of the University of California, through Lawrence Berkeley National Laboratory (subject to receipt of any required approvals from the U.S. Department of Energy) and contributors. All rights reserved.  # NOQA
:author
"""

import datetime

from django.utils import timezone as tz

from seed.data_importer.equivalence_partitioner import EquivalencePartitioner
from seed.data_importer.tasks import (
    match_buildings,
    save_state_match,
    filter_duplicated_states,
    match_and_merge_unmatched_objects,
)
from seed.models import (
    ASSESSED_RAW,
    DATA_STATE_MAPPING,
    DATA_STATE_DELETE,
    MERGE_STATE_MERGED,
    Column,
    Cycle,
    PropertyAuditLog,
    PropertyState,
    PropertyView,
    TaxLotProperty,
    TaxLotView,
)
from seed.test_helpers.fake import (
    FakePropertyFactory,
    FakePropertyStateFactory,
    FakeTaxLotStateFactory,
    FakeTaxLotViewFactory,
    FakePropertyViewFactory,
)
from seed.tests.util import DataMappingBaseTestCase


# from seed.data_importer.tasks import merge_unmatched_into_views


class TestMatching(DataMappingBaseTestCase):
    def setUp(self):
        selfvars = self.set_up(ASSESSED_RAW)
        self.user, self.org, self.import_file, self.import_record, self.cycle = selfvars

        self.property_factory = FakePropertyFactory(organization=self.org)
        self.property_state_factory = FakePropertyStateFactory(organization=self.org)
        self.property_view_factory = FakePropertyViewFactory(organization=self.org,
                                                             cycle=self.cycle)
        self.taxlot_state_factory = FakeTaxLotStateFactory(organization=self.org)
        self.taxlot_view_factory = FakeTaxLotViewFactory(organization=self.org, cycle=self.cycle)

    def test_match_properties_and_taxlots_with_address(self):
        # create an ImportFile for testing purposes. Seems like we would want to run this matching just on a
        # list of properties and taxlots.
        #
        # This emulates importing the following
        #   Address,                Jurisdiction Tax Lot
        #   742 Evergreen Terrace,  100;101;110;111

        lot_numbers = '100;101;110;111'
        for i in range(10):
            self.property_state_factory.get_property_state(
                address_line_1='742 Evergreen Terrace',
                lot_number=lot_numbers,
                import_file_id=self.import_file.id,
                data_state=DATA_STATE_MAPPING,
            )

        for lot_number in lot_numbers.split(';'):
            self.taxlot_state_factory.get_taxlot_state(
                address_line_1=None,
                jurisdiction_tax_lot_id=lot_number,
                import_file_id=self.import_file.id,
                data_state=DATA_STATE_MAPPING,
            )

        # for ps in PropertyState.objects.filter(organization=self.org):
        #     print("%s -- %s -- %s" % (ps.lot_number, ps.import_file_id, ps.address_line_1))

        # for tl in TaxLotState.objects.filter(organization=self.org):
        #     print("%s -- %s" % (tl.import_file_id, tl.jurisdiction_tax_lot_id))

        # set import_file mapping done so that matching can occur.
        self.import_file.mapping_done = True
        self.import_file.save()
        match_buildings(self.import_file.id)

        # for pv in PropertyView.objects.filter(state__organization=self.org):
        #     print("%s -- %s" % (pv.state, pv.cycle))

        # should only have 1 PropertyView and 4 taxlot views
        self.assertEqual(PropertyView.objects.filter(state__organization=self.org).count(), 1)
        self.assertEqual(TaxLotView.objects.filter(state__organization=self.org).count(), 4)
        pv = PropertyView.objects.filter(state__organization=self.org).first()

        # there should be 4 relationships in the TaxLotProperty associated with view, one each for the taxlots defined
        self.assertEqual(TaxLotProperty.objects.filter(property_view_id=pv).count(), 4)

    def test_match_properties_and_taxlots_with_address_no_lot_number(self):
        # create an ImportFile for testing purposes. Seems like we would want to run this matching just on a
        # list of properties and taxlots.
        #
        # This emulates importing the following
        #   Address,                Jurisdiction Tax Lot
        #   742 Evergreen Terrace,  100
        #   742 Evergreen Terrace,  101
        #   742 Evergreen Terrace,  110
        #   742 Evergreen Terrace,  111

        lot_numbers = '100;101;110;111'
        for lot_number in lot_numbers.split(';'):
            self.property_state_factory.get_property_state(
                address_line_1='742 Evergreen Terrace',
                lot_number=lot_number,
                import_file_id=self.import_file.id,
                data_state=DATA_STATE_MAPPING,
            )

            self.taxlot_state_factory.get_taxlot_state(
                address_line_1=None,
                jurisdiction_tax_lot_id=lot_number,
                import_file_id=self.import_file.id,
                data_state=DATA_STATE_MAPPING,
            )

        # for ps in PropertyState.objects.filter(organization=self.org):
        #     print("%s -- %s -- %s" % (ps.lot_number, ps.import_file_id, ps.address_line_1))

        # for tl in TaxLotState.objects.filter(organization=self.org):
        #     print("%s -- %s" % (tl.import_file_id, tl.jurisdiction_tax_lot_id))

        # set import_file mapping done so that matching can occur.
        self.import_file.mapping_done = True
        self.import_file.save()
        match_buildings(self.import_file.id)

        # for pv in PropertyView.objects.filter(state__organization=self.org):
        #     print("%s -- %s" % (pv.state, pv.cycle))

        # should only have 1 PropertyView and 4 taxlot views
        self.assertEqual(PropertyView.objects.filter(state__organization=self.org).count(), 1)
        self.assertEqual(TaxLotView.objects.filter(state__organization=self.org).count(), 4)
        pv = PropertyView.objects.filter(state__organization=self.org).first()

        # there should be 4 relationships in the TaxLotProperty associated with view, one each for the taxlots defined
        self.assertEqual(TaxLotProperty.objects.filter(property_view_id=pv).count(), 4)

    def test_match_properties_and_taxlots_with_ubid(self):
        # create an ImportFile for testing purposes. Seems like we would want to run this matching just on a
        # list of properties and taxlots.
        #
        # This emulates importing the following
        #   UBID,    Jurisdiction Tax Lot
        #   ubid_100,     lot_1
        #   ubid_101,     lot_1
        #   ubid_110,     lot_1
        #   ubid_111,     lot_1

        ids = [('ubid_100', 'lot_1'), ('ubid_101', 'lot_1'), ('ubid_110', 'lot_1'),
               ('ubid_111', 'lot_1')]
        for id in ids:
            self.property_state_factory.get_property_state(
                no_default_data=True,
                ubid=id[0],
                lot_number=id[1],
                import_file_id=self.import_file.id,
                data_state=DATA_STATE_MAPPING,
            )

        self.taxlot_state_factory.get_taxlot_state(
            no_default_data=True,
            jurisdiction_tax_lot_id=ids[0][1],
            import_file_id=self.import_file.id,
            data_state=DATA_STATE_MAPPING,
        )

        # for ps in PropertyState.objects.filter(organization=self.org):
        #     print("%s -- %s -- %s" % (ps.lot_number, ps.import_file_id, ps.ubid))
        # pv = PropertyView.objects.get(state=ps, cycle=self.cycle)
        # TaxLotProperty.objects.filter()

        # for tl in TaxLotState.objects.filter(organization=self.org):
        #     print("%s -- %s" % (tl.import_file_id, tl.jurisdiction_tax_lot_id))

        # set import_file mapping done so that matching can occur.
        self.import_file.mapping_done = True
        self.import_file.save()
        match_buildings(self.import_file.id)

        # for pv in PropertyView.objects.filter(state__organization=self.org):
        #     print("%s -- %s" % (pv.state.ubid, pv.cycle))

        # should only have 1 PropertyView and 4 taxlot views
        self.assertEqual(PropertyView.objects.filter(state__organization=self.org).count(), 4)
        self.assertEqual(TaxLotView.objects.filter(state__organization=self.org).count(), 1)
        tlv = TaxLotView.objects.filter(state__organization=self.org).first()

        # there should be 4 relationships in the TaxLotProperty associated with view, one each for the taxlots defined
        self.assertEqual(TaxLotProperty.objects.filter(taxlot_view_id=tlv).count(), 4)

    def test_match_properties_and_taxlots_with_custom_id(self):
        # create an ImportFile for testing purposes. Seems like we would want to run this matching just on a
        # list of properties and taxlots.
        #
        # This emulates importing the following
        #   Custom ID 1,    Jurisdiction Tax Lot
        #   custom_100,     lot_1
        #   custom_101,     lot_1
        #   custom_110,     lot_1
        #   custom_111,     lot_1
        ids = [('custom_100', 'lot_1'), ('custom_101', 'lot_1'), ('custom_110', 'lot_1'),
               ('custom_111', 'lot_1')]
        for id in ids:
            self.property_state_factory.get_property_state(
                no_default_data=True,
                custom_id_1=id[0],
                lot_number=id[1],
                import_file_id=self.import_file.id,
                data_state=DATA_STATE_MAPPING,
            )

        self.taxlot_state_factory.get_taxlot_state(
            no_default_data=True,
            jurisdiction_tax_lot_id=ids[0][1],
            import_file_id=self.import_file.id,
            data_state=DATA_STATE_MAPPING,
        )

        # for ps in PropertyState.objects.filter(organization=self.org):
        #     print("%s -- %s -- %s" % (ps.lot_number, ps.import_file_id, ps.custom_id_1))
        # pv = PropertyView.objects.get(state=ps, cycle=self.cycle)
        # TaxLotProperty.objects.filter()

        # for tl in TaxLotState.objects.filter(organization=self.org):
        #     print("%s -- %s" % (tl.import_file_id, tl.jurisdiction_tax_lot_id))

        # set import_file mapping done so that matching can occur.
        self.import_file.mapping_done = True
        self.import_file.save()
        match_buildings(self.import_file.id)

        # for pv in PropertyView.objects.filter(state__organization=self.org):
        #     print("%s -- %s" % (pv.state, pv.cycle))

        # should only have 1 PropertyView and 4 taxlot views
        self.assertEqual(PropertyView.objects.filter(state__organization=self.org).count(), 4)
        self.assertEqual(TaxLotView.objects.filter(state__organization=self.org).count(), 1)
        tlv = TaxLotView.objects.filter(state__organization=self.org).first()

        # there should be 4 relationships in the TaxLotProperty associated with view, one each for the taxlots defined
        self.assertEqual(TaxLotProperty.objects.filter(taxlot_view_id=tlv).count(), 4)

    def test_save_state_match(self):
        # create a couple states to merge together
        ps_1 = self.property_state_factory.get_property_state(property_name="this should persist")
        ps_2 = self.property_state_factory.get_property_state(
            extra_data={"extra_1": "this should exist too"})

        priorities = Column.retrieve_priorities(self.org.pk)
        merged_state = save_state_match(ps_1, ps_2, priorities)

        self.assertEqual(merged_state.merge_state, MERGE_STATE_MERGED)
        self.assertEqual(merged_state.property_name, ps_1.property_name)
        self.assertEqual(merged_state.extra_data['extra_1'], "this should exist too")

        # verify that the audit log is correct.
        pal = PropertyAuditLog.objects.get(organization=self.org, state=merged_state)
        self.assertEqual(pal.name, 'System Match')
        self.assertEqual(pal.parent_state1, ps_1)
        self.assertEqual(pal.parent_state2, ps_2)
        self.assertEqual(pal.description, 'Automatic Merge')

    def test_filter_duplicated_states(self):
        for i in range(10):
            self.property_state_factory.get_property_state(
                no_default_data=True,
                address_line_1='123 The Same Address',
                # extra_data={"extra_1": "value_%s" % i},
                import_file_id=self.import_file.id,
                data_state=DATA_STATE_MAPPING,
            )
        for i in range(5):
            self.property_state_factory.get_property_state(
                import_file_id=self.import_file.id,
                data_state=DATA_STATE_MAPPING,
            )

        props = self.import_file.find_unmatched_property_states()
        uniq_states, dup_states = filter_duplicated_states(props)

        # There should be 6 uniq states. 5 from the second call, and one of 'The Same Address'
        self.assertEqual(len(uniq_states), 6)
        self.assertEqual(len(dup_states), 9)

    def test_match_and_merge_unmatched_objects_all_unique(self):
        # create some objects to match and merge
        partitioner = EquivalencePartitioner.make_default_state_equivalence(PropertyState)

        for i in range(10):
            self.property_state_factory.get_property_state(
                import_file_id=self.import_file.id,
                data_state=DATA_STATE_MAPPING,
            )

        props = self.import_file.find_unmatched_property_states()
        uniq_states, dup_states = filter_duplicated_states(props)
        merged, keys = match_and_merge_unmatched_objects(uniq_states, partitioner)

        self.assertEqual(len(merged), 10)

    def test_match_and_merge_unmatched_objects_with_duplicates(self):
        # create some objects to match and merge
        partitioner = EquivalencePartitioner.make_default_state_equivalence(PropertyState)

        for i in range(8):
            self.property_state_factory.get_property_state(
                import_file_id=self.import_file.id,
                data_state=DATA_STATE_MAPPING,
            )

        self.property_state_factory.get_property_state(
            no_default_data=True,
            extra_data={'moniker': '12345'},
            address_line_1='123 same address',
            site_eui=25,
            import_file_id=self.import_file.id,
            data_state=DATA_STATE_MAPPING,
        )

        self.property_state_factory.get_property_state(
            no_default_data=True,
            extra_data={'moniker': '12345'},
            address_line_1='123 same address',
            site_eui=150,
            import_file_id=self.import_file.id,
            data_state=DATA_STATE_MAPPING,
        )

        props = self.import_file.find_unmatched_property_states()
        uniq_states, dup_states = filter_duplicated_states(props)
        merged, keys = match_and_merge_unmatched_objects(uniq_states, partitioner)

        self.assertEqual(len(merged), 9)
        self.assertEqual(len(keys), 9)

        # find the ps_cp_1 in the list of merged
        found = False
        for ps in merged:
            if ps.extra_data.get('moniker', None) == '12345':
                found = True
                self.assertEqual(ps.site_eui.magnitude, 150)  # from the second record
        self.assertEqual(found, True)

    def test_match_and_merge_unmatched_objects_with_dates(self):
        # Make sure that the dates sort correctly! (only testing release_date, but also sorts
        # on generation_date, then pk

        partitioner = EquivalencePartitioner.make_default_state_equivalence(PropertyState)

        self.property_state_factory.get_property_state(
            no_default_data=True,
            address_line_1='123 same address',
            release_date=datetime.datetime(2010, 1, 1, 1, 1, tzinfo=tz.get_current_timezone()),
            site_eui=25,
            import_file_id=self.import_file.id,
            data_state=DATA_STATE_MAPPING,
        )

        self.property_state_factory.get_property_state(
            no_default_data=True,
            address_line_1='123 same address',
            release_date=datetime.datetime(2015, 1, 1, 1, 1, tzinfo=tz.get_current_timezone()),
            site_eui=150,
            import_file_id=self.import_file.id,
            data_state=DATA_STATE_MAPPING,
        )

        self.property_state_factory.get_property_state(
            no_default_data=True,
            address_line_1='123 same address',
            release_date=datetime.datetime(2005, 1, 1, 1, 1, tzinfo=tz.get_current_timezone()),
            site_eui=300,
            import_file_id=self.import_file.id,
            data_state=DATA_STATE_MAPPING,
        )

        props = self.import_file.find_unmatched_property_states()
        uniq_states, dup_states = filter_duplicated_states(props)
        merged, keys = match_and_merge_unmatched_objects(uniq_states, partitioner)

        found = False
        for ps in merged:
            found = True
            self.assertEqual(ps.site_eui.magnitude, 150)  # from the second record
        self.assertEqual(found, True)

    def test_merge_unmatched_into_views_no_matches(self):
        """It is very unlikely that any of these states will match since it is using faker."""
        for i in range(10):
            self.property_state_factory.get_property_state(
                import_file_id=self.import_file.id,
                data_state=DATA_STATE_MAPPING,
            )

        # merge_unmatched_into_views(unmatched_states, partitioner, org, import_file):

    def test_match_within_cycle_two_different_import_files(self):
        ps_1 = self.property_state_factory.get_property_state(
            no_default_data=True,
            extra_data={'moniker': '12345'},
            address_line_1='123 same address',
            site_eui=25,
            import_file_id=self.import_file.id,
            data_state=DATA_STATE_MAPPING,
        )

        self.import_file.mapping_done = True
        self.import_file.save()
        match_buildings(self.import_file.id)

        # Sanity check that only 1 PropertyView exists
        self.assertEqual(1, PropertyView.objects.count())

        _import_record, new_import_file = self.create_import_file(
            self.user, self.org, self.cycle
        )

        ps_2 = PropertyState.objects.get(pk=ps_1.id)
        ps_2.pk = None
        ps_2.import_file_id = new_import_file.id
        ps_2.data_state = DATA_STATE_MAPPING
        ps_2.save()

        new_import_file.mapping_done = True
        new_import_file.save()
        match_buildings(new_import_file.id)

        refreshed_ps_2 = PropertyState.objects.get(import_file_id=new_import_file.id)

        # still 1 PropertyView, latest State is marked for deletion
        self.assertEqual(1, PropertyView.objects.count())
        self.assertEqual(DATA_STATE_DELETE, refreshed_ps_2.data_state)

    def test_match_states_across_cycles(self):
        """
        Matching across cycles relies on the same matching logic as matching
        within cycles tested above.

        Because of that, this test will only test matching on
        - address_line_1 for PropertyStates
        - jurisdiction_tax_lot_id for TaxLotStates
        rather than testing on different fields.
        """

        # Create 2 properties and 2 tax lots in first cycle
        for i in range(2):
            self.property_state_factory.get_property_state(
                address_line_1='{} Evergreen Terrace'.format(i),
                import_file_id=self.import_file.id,
                data_state=DATA_STATE_MAPPING,
            )

        lot_numbers = '100;101'
        for lot_number in lot_numbers.split(';'):
            self.taxlot_state_factory.get_taxlot_state(
                address_line_1=None,
                jurisdiction_tax_lot_id=lot_number,
                import_file_id=self.import_file.id,
                data_state=DATA_STATE_MAPPING,
            )

        self.import_file.mapping_done = True
        self.import_file.save()
        match_buildings(self.import_file.id)

        # Create new cycle and import_file within same org for new properties and tax lots
        new_cycle, _ = Cycle.objects.get_or_create(
            name='Test Hack Cycle 1984',
            organization=self.org,
            start=datetime.datetime(2015, 1, 1, tzinfo=tz.get_current_timezone()),
            end=datetime.datetime(2015, 12, 31, tzinfo=tz.get_current_timezone()),
        )

        _import_record, new_import_file = self.create_import_file(
            self.user, self.org, new_cycle
        )

        # Create 3 properties and 3 tax lots for new cycle (1 non-matching each)
        for i in range(3):
            self.property_state_factory.get_property_state(
                address_line_1='{} Evergreen Terrace'.format(i),
                import_file_id=new_import_file.id,
                data_state=DATA_STATE_MAPPING,
            )

        lot_numbers = '100;101;109'
        for lot_number in lot_numbers.split(';'):
            self.taxlot_state_factory.get_taxlot_state(
                address_line_1=None,
                jurisdiction_tax_lot_id=lot_number,
                import_file_id=new_import_file.id,
                data_state=DATA_STATE_MAPPING,
            )

        new_import_file.mapping_done = True
        new_import_file.save()
        match_buildings(new_import_file.id)

        # Check that -States are associated across Cycle by Property/TaxLot (via -Views)
        # Each of those Property/TaxLots should have 2 Views associated to it now
        pv0_new_cycle = PropertyView.objects.select_related('state').get(state__address_line_1='0 Evergreen Terrace', state__import_file_id=new_import_file.id)
        pv0_old_cycle = PropertyView.objects.select_related('state').get(state__address_line_1='0 Evergreen Terrace', state__import_file_id=self.import_file.id)
        self.assertEqual(pv0_new_cycle.property, pv0_old_cycle.property)
        self.assertNotEqual(pv0_new_cycle.cycle, pv0_old_cycle.cycle)
        self.assertEqual(pv0_new_cycle.property.views.count(), 2)

        pv1_new_cycle = PropertyView.objects.select_related('state').get(state__address_line_1='1 Evergreen Terrace', state__import_file_id=new_import_file.id)
        pv1_old_cycle = PropertyView.objects.select_related('state').get(state__address_line_1='1 Evergreen Terrace', state__import_file_id=self.import_file.id)
        self.assertEqual(pv1_new_cycle.property, pv1_old_cycle.property)
        self.assertNotEqual(pv1_new_cycle.cycle, pv1_old_cycle.cycle)
        self.assertEqual(pv1_new_cycle.property.views.count(), 2)

        tlv0_new_cycle = TaxLotView.objects.select_related('state').get(state__jurisdiction_tax_lot_id='100', state__import_file_id=new_import_file.id)
        tlv0_old_cycle = TaxLotView.objects.select_related('state').get(state__jurisdiction_tax_lot_id='100', state__import_file_id=self.import_file.id)
        self.assertEqual(tlv0_new_cycle.taxlot, tlv0_old_cycle.taxlot)
        self.assertNotEqual(tlv0_new_cycle.cycle, tlv0_old_cycle.cycle)
        self.assertEqual(tlv0_new_cycle.taxlot.views.count(), 2)

        tlv1_new_cycle = TaxLotView.objects.select_related('state').get(state__jurisdiction_tax_lot_id='101', state__import_file_id=new_import_file.id)
        tlv1_old_cycle = TaxLotView.objects.select_related('state').get(state__jurisdiction_tax_lot_id='101', state__import_file_id=self.import_file.id)
        self.assertEqual(tlv1_new_cycle.taxlot, tlv1_old_cycle.taxlot)
        self.assertNotEqual(tlv1_new_cycle.cycle, tlv1_old_cycle.cycle)
        self.assertEqual(tlv1_new_cycle.taxlot.views.count(), 2)

        # As before, a -State without a match should have its Property/TaxLot that has only 1 associated -View
        pv2_new_cycle = PropertyView.objects.select_related('state').get(state__address_line_1='2 Evergreen Terrace', state__import_file_id=new_import_file.id)
        self.assertNotEqual(pv2_new_cycle.property, pv0_old_cycle.property)
        self.assertNotEqual(pv2_new_cycle.property, pv1_old_cycle.property)
        self.assertEqual(pv2_new_cycle.property.views.count(), 1)

        tlv9_new_cycle = TaxLotView.objects.select_related('state').get(state__jurisdiction_tax_lot_id='109', state__import_file_id=new_import_file.id)
        self.assertNotEqual(tlv9_new_cycle.taxlot, tlv0_old_cycle.taxlot)
        self.assertNotEqual(tlv9_new_cycle.taxlot, tlv1_old_cycle.taxlot)
        self.assertEqual(tlv9_new_cycle.taxlot.views.count(), 1)
