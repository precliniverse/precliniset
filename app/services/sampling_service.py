# app/services/sampling_service.py
from datetime import date, datetime

from flask import current_app

from app.extensions import db
from app.helpers import generate_display_id
from app.models import (Anticoagulant, DerivedSampleType, Sample, SampleStatus,
                        SampleType, Storage, TissueCondition)
from app.services.base import BaseService


class SamplingService(BaseService):
    model = Sample

    def log_batch_samples(self, group, common_details, sample_set, animal_indices):
        """
        Logs a batch of samples for specific animals in a group based on a template set.
        Returns: (created_count, errors_list)
        """
        samples_created_count = 0
        batch_errors = []

        try:
            collection_date = datetime.fromisoformat(common_details['collection_date']).date()
        except ValueError:
            return 0, ["Invalid collection date format."]

        is_terminal = common_details.get('is_terminal_event', False)
        default_status = SampleStatus[common_details.get('status', 'STORED')]
        default_storage_id = common_details.get('default_storage_id')
        event_notes = common_details.get('event_notes')

        # Handle terminal event status update for animals
        if is_terminal:
            for animal_idx in animal_indices:
                if 0 <= animal_idx < len(group.animal_data):
                    group.animal_data[animal_idx]['status'] = 'dead'
                    group.animal_data[animal_idx]['death_date'] = collection_date.isoformat()
            # We don't commit here, we let the caller or the final commit handle it
            # But we need to flag modified if we are modifying the JSON
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(group, "animal_data")

        for animal_idx in animal_indices:
            for sample_template in sample_set:
                try:
                    sample_type_str = sample_template['sample_type']
                    sample_type = SampleType[sample_type_str]
                    
                    # Common attributes for this template
                    specific_notes = sample_template.get('specific_notes')
                    final_notes = specific_notes or event_notes
                    storage_id_override = sample_template.get('storage_id_override')
                    final_storage_id = int(storage_id_override) if storage_id_override else (int(default_storage_id) if default_storage_id else None)

                    # --- BIOLOGICAL TISSUE LOGIC ---
                    if sample_type == SampleType.BIOLOGICAL_TISSUE:
                        for organ_detail in sample_template.get('tissue_details_json', []):
                            condition_ids = organ_detail.get('condition_ids', [])
                            if not condition_ids:
                                batch_errors.append(f"No collection conditions selected for organ ID {organ_detail.get('organ_id')} (Animal Index {animal_idx}).")
                                continue

                            # Create a separate sample for EACH condition
                            for condition_id in condition_ids:
                                condition = db.session.get(TissueCondition, int(condition_id))
                                if not condition:
                                    batch_errors.append(f"Invalid condition ID {condition_id} found.")
                                    continue

                                organ_storage_id = organ_detail.get('storage_id')
                                effective_storage_id = int(organ_storage_id) if organ_storage_id else final_storage_id
                                organ_notes = organ_detail.get('notes') or final_notes

                                new_sample = Sample(
                                    experimental_group_id=group.id,
                                    animal_index_in_group=animal_idx,
                                    collection_date=collection_date,
                                    is_terminal=is_terminal,
                                    status=default_status,
                                    notes=organ_notes,
                                    sample_type=sample_type,
                                    display_id=generate_display_id(group),
                                    piece_id=organ_detail.get('piece_id'),
                                    organ_id=organ_detail.get('organ_id'),
                                    storage_id=effective_storage_id
                                )
                                
                                new_sample.collection_conditions = [condition]
                                db.session.add(new_sample)
                                samples_created_count += 1
                    
                    # --- OTHER SAMPLE TYPES ---
                    else:
                        new_sample = Sample(
                            experimental_group_id=group.id,
                            animal_index_in_group=animal_idx,
                            collection_date=collection_date,
                            is_terminal=is_terminal,
                            status=default_status,
                            notes=final_notes,
                            sample_type=sample_type,
                            display_id=generate_display_id(group),
                            storage_id=final_storage_id
                        )

                        if sample_type == SampleType.BLOOD:
                            if sample_template.get('anticoagulant_id'): 
                                new_sample.anticoagulant_id = int(sample_template['anticoagulant_id'])
                            if sample_template.get('blood_volume'): 
                                new_sample.volume = float(sample_template['blood_volume'])
                            new_sample.volume_unit = sample_template.get('blood_volume_unit') or 'µL'
                        
                        elif sample_type == SampleType.URINE:
                            if sample_template.get('urine_volume'): 
                                new_sample.volume = float(sample_template['urine_volume'])
                            new_sample.volume_unit = sample_template.get('urine_volume_unit') or 'µL'
                        
                        elif sample_type == SampleType.OTHER and sample_template.get('other_description'):
                            desc = sample_template['other_description']
                            new_sample.notes = f"Other Desc: {desc}\n{new_sample.notes or ''}".strip()

                        db.session.add(new_sample)
                        samples_created_count += 1

                except Exception as e:
                    batch_errors.append(f"Error for animal index {animal_idx}: {str(e)}")
                    current_app.logger.error(f"Error creating sample in service: {e}", exc_info=True)

        if not batch_errors:
            db.session.commit()
        else:
            db.session.rollback()
            
        return samples_created_count, batch_errors

    def create_derived_samples(self, group, parent_sample_ids, derivation_plan, common_details, update_parent_status=False):
        """
        Creates derived samples from a list of parent samples based on a plan.
        Returns: (created_count, errors_list)
        """
        samples_created_count = 0
        batch_errors = []

        try:
            collection_date = datetime.fromisoformat(common_details['collection_date']).date()
        except ValueError:
            return 0, ["Invalid collection date format."]

        is_terminal = common_details.get('is_terminal_event', False)
        default_storage_id = common_details.get('default_storage_id')
        event_notes = common_details.get('event_notes')

        parent_samples_map = {s.id: s for s in Sample.query.filter(Sample.id.in_(parent_sample_ids)).all()}

        # --- Volume Pre-check ---
        total_volume_to_derive = sum(
            float(d.get('volume', 0) or 0) * int(d.get('quantity', 1)) 
            for d in derivation_plan if d.get('volume')
        )
        
        if total_volume_to_derive > 0:
            for parent_id in parent_sample_ids:
                parent_sample = parent_samples_map.get(parent_id)
                if parent_sample and parent_sample.volume is not None:
                    if total_volume_to_derive > parent_sample.volume:
                        batch_errors.append(f"Plan requires {total_volume_to_derive}{parent_sample.volume_unit} but parent {parent_sample.display_id or parent_id} only has {parent_sample.volume}{parent_sample.volume_unit}.")

        if batch_errors:
            return 0, batch_errors

        # --- Creation Loop ---
        for parent_id in parent_sample_ids:
            parent_sample = parent_samples_map.get(parent_id)
            if not parent_sample:
                batch_errors.append(f"Parent sample with ID {parent_id} not found.")
                continue

            for plan_item in derivation_plan:
                quantity = int(plan_item.get('quantity', 1))
                derived_type_id = int(plan_item['derived_type_id'])
                
                # Fetch derived type object to ensure it exists (optional but good practice)
                # derived_type = db.session.get(DerivedSampleType, derived_type_id)

                storage_id = plan_item.get('storage_id') or default_storage_id
                final_storage_id = int(storage_id) if storage_id else None
                
                final_notes = plan_item.get('notes') or event_notes

                for _ in range(quantity):
                    new_sample = Sample(
                        experimental_group_id=group.id,
                        animal_index_in_group=parent_sample.animal_index_in_group,
                        parent_sample_id=parent_sample.id,
                        collection_date=collection_date,
                        is_terminal=is_terminal,
                        notes=final_notes,
                        sample_type=parent_sample.sample_type,
                        derived_type_id=derived_type_id,
                        display_id=generate_display_id(group, parent_sample=parent_sample),
                        storage_id=final_storage_id,
                        volume=plan_item.get('volume') or None,
                        volume_unit=parent_sample.volume_unit,
                        organ_id=parent_sample.organ_id,
                        staining_id=plan_item.get('staining_id') or None,
                        status=SampleStatus.STORED # Default for derived
                    )
                    db.session.add(new_sample)
                    samples_created_count += 1

            # Update parent sample volume and status
            if parent_sample.volume is not None and total_volume_to_derive > 0:
                parent_sample.volume -= total_volume_to_derive
            
            if update_parent_status:
                parent_sample.status = SampleStatus.USED_FOR_DERIVATION
            
            db.session.add(parent_sample)

        if not batch_errors:
            db.session.commit()
        else:
            db.session.rollback()

        return samples_created_count, batch_errors

    def batch_update_status(self, sample_ids, new_status, destination=None):
        """
        Updates status for a list of samples, handling dates and notes.
        """
        samples = Sample.query.filter(Sample.id.in_(sample_ids)).all()
        updated_count = 0
        today = date.today()
        today_str = today.isoformat()

        for sample in samples:
            sample.status = new_status
            
            if new_status == SampleStatus.SHIPPED:
                sample.shipment_date = today
                sample.destruction_date = None
                if destination:
                    note_update = f"Shipped to {destination} on {today_str}."
                    sample.notes = f"{sample.notes}\n{note_update}" if sample.notes else note_update
            
            elif new_status == SampleStatus.DESTROYED:
                sample.destruction_date = today
                sample.shipment_date = None
                note_update = f"Destroyed on {today_str}."
                sample.notes = f"{sample.notes}\n{note_update}" if sample.notes else note_update
            
            elif new_status == SampleStatus.STORED:
                # Reset dates if moving back to stored
                sample.shipment_date = None
                sample.destruction_date = None

            updated_count += 1

        db.session.commit()
        return updated_count

    def batch_change_storage(self, sample_ids, new_storage_id):
        """
        Updates storage location for a list of samples.
        """
        samples = Sample.query.filter(Sample.id.in_(sample_ids)).all()
        count = 0
        for sample in samples:
            sample.storage_id = new_storage_id
            count += 1
        db.session.commit()
        return count

    def build_sample_query(self, user, filters):
        """
        Constructs a SQLAlchemy query for Samples based on user permissions and filters.
        Used by both DataTables and Batch Actions.
        """
        from app.models import Sample, ExperimentalGroup, Project, SampleStatus, SampleType
        from sqlalchemy import or_, func, cast
        from app.extensions import db

        # 1. Base Query & Permissions
        query = Sample.query.join(ExperimentalGroup).join(Project)
        
        if not user.is_super_admin:
            user_teams = user.get_teams()
            user_team_ids = [t.id for t in user_teams] if user_teams else []
            query = query.filter(Project.team_id.in_(user_team_ids))

        # 2. Apply Filters
        if filters.get('group_id'):
            query = query.filter(ExperimentalGroup.id == filters['group_id'])
        elif filters.get('project_slug'):
            query = query.filter(Project.slug == filters['project_slug'])
            
        # Status Filter
        status_filter = filters.get('status_filter')
        if status_filter and status_filter != 'all':
            # Handle both list and comma-separated string
            if isinstance(status_filter, str):
                statuses = status_filter.split(',')
            else:
                statuses = status_filter
            
            status_enums = []
            for s in statuses:
                try: status_enums.append(SampleStatus[s])
                except KeyError: pass
            if status_enums: query = query.filter(Sample.status.in_(status_enums))

        # Archive Filtering ---
        # Check if 'show_archived' is in filters (passed from batch action payload)
        # Default to False (Active Only) if not specified, for safety in batch ops
        show_archived = filters.get('show_archived') == 'true' or filters.get('show_archived') is True
        
        if not show_archived:
             query = query.filter(
                ExperimentalGroup.is_archived == False,
                Project.is_archived == False
            )

        # Type Filter
        if filters.get('sample_type'):
            try: query = query.filter(Sample.sample_type == SampleType[filters['sample_type']])
            except KeyError: pass

        # ID Filters
        if filters.get('organ_id'):
            query = query.filter(Sample.organ_id == filters['organ_id'])
        if filters.get('storage_id'):
            query = query.filter(Sample.storage_id == filters['storage_id'])
        if filters.get('condition_id'):
            query = query.filter(Sample.collection_conditions.any(id=filters['condition_id']))

        # Date Filters
        if filters.get('date_from'):
            try:
                d_from = datetime.strptime(filters['date_from'], '%Y-%m-%d').date()
                query = query.filter(Sample.collection_date >= d_from)
            except ValueError: pass
        if filters.get('date_to'):
            try:
                d_to = datetime.strptime(filters['date_to'], '%Y-%m-%d').date()
                query = query.filter(Sample.collection_date <= d_to)
            except ValueError: pass

        # Global Search
        search_value = filters.get('search_value')
        if search_value:
            search_pattern = f"%{search_value}%"
            query = query.filter(or_(
                Sample.display_id.ilike(search_pattern),
                cast(Sample.id, db.String).ilike(search_pattern),
                ExperimentalGroup.name.ilike(search_pattern),
                Project.name.ilike(search_pattern),
                Sample.notes.ilike(search_pattern)
            ))
            
        return query