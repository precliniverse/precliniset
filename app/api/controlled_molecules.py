# app/api/controlled_molecules.py
from datetime import datetime

from flask import jsonify, request, url_for
from sqlalchemy import func

from app.api import api_bp
from app.api.auth import token_required
from app.models import (ControlledMolecule, DataTable, DataTableMoleculeUsage,
                         ExperimentalGroup, ProtocolMoleculeAssociation,
                         RegulationCategory, User, user_has_permission)


@api_bp.route('/controlled_molecules', methods=['GET'])
@token_required
def get_controlled_molecules(current_user):
    """
    Get list of all controlled molecules.
    Permission: ControlledMolecule.View
    """
    if not user_has_permission(current_user, 'ControlledMolecule', 'View'):
        return jsonify({'message': 'Permission denied'}), 403

    molecules = ControlledMolecule.query.filter_by(is_active=True).all()
    results = []
    for m in molecules:
        results.append({
            'id': m.id,
            'name': m.name,
            'category': m.regulation_category.name,
            'category_label': m.regulation_category.value,
            'cas_number': m.cas_number,
            'internal_reference': m.internal_reference,
            'unit': m.unit,
            'responsible': m.responsible.username if m.responsible else None,
            'links': {
                'self': url_for('api.get_controlled_molecule', id=m.id, _external=True),
                'usage': url_for('api.get_molecule_usage', id=m.id, _external=True)
            }
        })

    return jsonify({
        'count': len(results),
        'molecules': results
    })


@api_bp.route('/controlled_molecules/<int:id>', methods=['GET'])
@token_required
def get_controlled_molecule(current_user, id):
    """
    Get details of a specific controlled molecule.
    Permission: ControlledMolecule.View
    """
    if not user_has_permission(current_user, 'ControlledMolecule', 'View'):
        return jsonify({'message': 'Permission denied'}), 403

    molecule = ControlledMolecule.query.get_or_404(id)
    return jsonify(molecule.to_dict())


@api_bp.route('/controlled_molecules/<int:id>/usage', methods=['GET'])
@token_required
def get_molecule_usage(current_user, id):
    """
    Get usage history for a molecule.
    Query params: start_date (YYYY-MM-DD), end_date (YYYY-MM-DD), project_id
    Permission: ControlledMolecule.View
    """
    if not user_has_permission(current_user, 'ControlledMolecule', 'View'):
        return jsonify({'message': 'Permission denied'}), 403

    molecule = ControlledMolecule.query.get_or_404(id)
    
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    project_id = request.args.get('project_id', type=int)

    query = DataTableMoleculeUsage.query.join(DataTable).join(ExperimentalGroup)
    
    query = query.filter(DataTableMoleculeUsage.molecule_id == id)
    
    if start_date:
        query = query.filter(DataTable.date >= start_date)
    if end_date:
        query = query.filter(DataTable.date <= end_date)
    if project_id:
        query = query.filter(ExperimentalGroup.project_id == project_id)
        
    usage_records = query.order_by(DataTable.date.desc()).all()
    
    results = []
    for usage in usage_records:
        data = usage.to_dict()
        # Enrich with context
        data['date'] = usage.data_table.date
        data['group_name'] = usage.data_table.group.name
        data['project_id'] = usage.data_table.group.project_id
        data['protocol_id'] = usage.data_table.protocol_id
        results.append(data)

    return jsonify({
        'molecule': molecule.name,
        'count': len(results),
        'total_volume': sum(float(r['volume_used']) for r in results if r['volume_used']),
        'usage_records': results
    })


@api_bp.route('/controlled_molecules/compliance_check', methods=['GET'])
@token_required
def check_compliance(current_user):
    """
    Check for compliance issues.
    Returns molecules with missing responsible person or other alerts.
    Permission: ControlledMolecule.View
    """
    if not user_has_permission(current_user, 'ControlledMolecule', 'View'):
        return jsonify({'message': 'Permission denied'}), 403

    alerts = []
    
    # Check 1: Active molecules without responsible person
    orphan_molecules = ControlledMolecule.query.filter(
        ControlledMolecule.is_active == True,
        ControlledMolecule.responsible_id == None
    ).all()
    
    for m in orphan_molecules:
        alerts.append({
            'type': 'missing_responsible',
            'molecule_id': m.id,
            'molecule_name': m.name,
            'message': f"Controlled molecule '{m.name}' has no responsible person designated."
        })

    return jsonify({
        'alert_count': len(alerts),
        'alerts': alerts
    })
