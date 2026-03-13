"""Sync routes for auth-service permission discovery."""
from flask import Blueprint, jsonify
from permissions_setup import permissions_registry

sync_bp = Blueprint('sync', __name__)


@sync_bp.route('/permissions', methods=['GET', 'POST'])
def get_service_permissions():
    """Return all available permissions for this service.
    Called by auth-service during permission sync."""
    try:
        all_perms = permissions_registry.get_all_permissions()
        return jsonify({
            "success": True,
            "service_key": "finder",
            "permissions": permissions_registry.to_dict()["permissions"],
            "total_permissions": len(all_perms),
            "categories": list(set(p.category for p in all_perms if p.category))
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
