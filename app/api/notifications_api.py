# app/api/notifications_api.py
from flask import jsonify, request
from flask_login import current_user, login_required

from app import db
from app.api import api_bp
from app.models.notifications import Notification


@api_bp.route('/notifications', methods=['GET'])
@login_required
def get_notifications():
    """Retourne les notifications non lues de l'utilisateur courant."""
    limit = request.args.get('limit', 20, type=int)
    unread_only = request.args.get('unread_only', 'true').lower() == 'true'

    query = Notification.query.filter_by(user_id=current_user.id)
    if unread_only:
        query = query.filter_by(is_read=False)

    notifications = query.order_by(Notification.created_at.desc()).limit(limit).all()
    unread_count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()

    return jsonify({
        'notifications': [n.to_dict() for n in notifications],
        'unread_count': unread_count
    })


@api_bp.route('/notifications/<int:notif_id>/read', methods=['POST'])
@login_required
def mark_notification_read(notif_id):
    """Marque une notification comme lue."""
    notif = Notification.query.filter_by(id=notif_id, user_id=current_user.id).first_or_404()
    notif.is_read = True
    db.session.commit()
    return jsonify({'success': True})


@api_bp.route('/notifications/read_all', methods=['POST'])
@login_required
def mark_all_notifications_read():
    """Marque toutes les notifications de l'utilisateur comme lues."""
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    return jsonify({'success': True})


@api_bp.route('/notifications/<int:notif_id>', methods=['DELETE'])
@login_required
def delete_notification(notif_id):
    """Supprime une notification."""
    notif = Notification.query.filter_by(id=notif_id, user_id=current_user.id).first_or_404()
    db.session.delete(notif)
    db.session.commit()
    return jsonify({'success': True})
