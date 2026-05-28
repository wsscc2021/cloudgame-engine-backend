from flask import jsonify


def success(data=None, message="success", status=200):
    body = {"success": True, "message": message}
    if data is not None:
        body["data"] = data
    return jsonify(body), status


def error(message="error", status=400):
    return jsonify({"success": False, "message": message}), status
