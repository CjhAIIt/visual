#!/usr/bin/env python3
import io
import json
import mimetypes
import os
import shutil
import sqlite3
import struct
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path


BASE_URL = os.getenv("PLANT_API_BASE_URL", "http://127.0.0.1:7800").rstrip("/")
ADMIN_USERNAME = os.getenv("PLANT_ADMIN_USERNAME") or os.getenv("BOOTSTRAP_ADMIN_USERNAME", "root")
ADMIN_PASSWORD = os.getenv("PLANT_ADMIN_PASSWORD") or os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "root")
USER_USERNAME = os.getenv("PLANT_USER_USERNAME") or os.getenv("BOOTSTRAP_USER_USERNAME", "root_user")
USER_PASSWORD = os.getenv("PLANT_USER_PASSWORD") or os.getenv("BOOTSTRAP_USER_PASSWORD", "root")
THIRD_USERNAME = os.getenv("PLANT_THIRD_USERNAME", "123")
THIRD_PASSWORD = os.getenv("PLANT_THIRD_PASSWORD", "1234")

ROOT = Path(__file__).resolve().parents[1]
SOURCE_MODEL = ROOT / "plantbackend/models/best.onnx"
DB_PATH = ROOT / "plantbackend/plant_auth.db"


class CheckFailure(RuntimeError):
    pass


def log(message):
    print(message, flush=True)


def assert_true(condition, message):
    if not condition:
        raise CheckFailure(message)


def request(
    path,
    *,
    method="GET",
    token=None,
    json_payload=None,
    multipart_fields=None,
    multipart_files=None,
    expected_status=200,
    parse_json=True,
):
    url = f"{BASE_URL}{path}"
    headers = {}
    data = None

    if token:
        headers["X-Auth-Token"] = token

    if json_payload is not None:
        data = json.dumps(json_payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif multipart_fields is not None or multipart_files is not None:
        content_type, data = build_multipart(multipart_fields or {}, multipart_files or {})
        headers["Content-Type"] = content_type

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read()
            status = resp.getcode()
            resp_headers = dict(resp.headers.items())
    except urllib.error.HTTPError as exc:
        body = exc.read()
        status = exc.code
        resp_headers = dict(exc.headers.items())

    if status != expected_status:
        body_text = body.decode("utf-8", "ignore")
        raise CheckFailure(f"{method} {path} expected {expected_status}, got {status}: {body_text}")

    if parse_json:
        try:
            return json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise CheckFailure(f"{method} {path} did not return valid JSON") from exc
    return body, resp_headers


def build_multipart(fields, files):
    boundary = f"----plant-{uuid.uuid4().hex}"
    body = io.BytesIO()

    def write(value):
        if isinstance(value, str):
            value = value.encode("utf-8")
        body.write(value)

    for name, value in fields.items():
        write(f"--{boundary}\r\n")
        write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n')
        write(str(value))
        write("\r\n")

    for field_name, file_info in files.items():
        filename = file_info["filename"]
        content = file_info["content"]
        content_type = file_info.get("content_type") or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        write(f"--{boundary}\r\n")
        write(
            f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
        )
        write(f"Content-Type: {content_type}\r\n\r\n")
        write(content)
        write("\r\n")

    write(f"--{boundary}--\r\n")
    return f"multipart/form-data; boundary={boundary}", body.getvalue()


def login(username, password):
    payload = request(
        "/auth/login",
        method="POST",
        json_payload={"username": username, "password": password},
    )
    token = str(payload.get("data", {}).get("token") or "")
    assert_true(token, f"Login token missing for {username}")
    return token, payload


def register_user(username, password, display_name=None):
    payload = request(
        "/auth/register",
        method="POST",
        json_payload={
            "username": username,
            "password": password,
            "display_name": display_name or username,
        },
    )
    token = str(payload.get("data", {}).get("token") or "")
    assert_true(token, f"Register token missing for {username}")
    return token, payload


def try_login(username, password):
    try:
        return login(username, password)
    except Exception:
        return None, None


def find_user(users_payload, username):
    for item in users_payload.get("data", {}).get("users", []):
        if str(item.get("username") or "") == username:
            return item
    return None


def find_model_item(models_payload, model_name):
    for item in models_payload.get("data", {}).get("available_model_items", []):
        if str(item.get("name") or "") == model_name:
            return item
    return None


def create_sample_bmp_bytes(width=96, height=96, color=(84, 150, 76)):
    row_padding = (4 - (width * 3) % 4) % 4
    pixel_data = bytearray()
    blue, green, red = color
    for _ in range(height):
        pixel_data.extend(bytes((blue, green, red)) * width)
        pixel_data.extend(b"\x00" * row_padding)

    pixel_offset = 14 + 40
    file_size = pixel_offset + len(pixel_data)
    dib_header = struct.pack(
        "<IIIHHIIIIII",
        40,
        width,
        height,
        1,
        24,
        0,
        len(pixel_data),
        2835,
        2835,
        0,
        0,
    )
    file_header = struct.pack("<2sIHHI", b"BM", file_size, 0, 0, pixel_offset)
    return file_header + dib_header + bytes(pixel_data)


def write_sample_image(target_path):
    target_path.write_bytes(create_sample_bmp_bytes())
    return target_path.name


def build_sample_dataset_zip(target_path):
    image_bytes = create_sample_bmp_bytes()
    label_text = "0 0.5 0.5 0.5 0.5\n"
    with zipfile.ZipFile(target_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("classes.txt", "smoke_leaf\n")
        for split in ("raw", "train", "val"):
            archive.writestr(f"images/{split}/sample.bmp", image_bytes)
            archive.writestr(f"labels/{split}/sample.txt", label_text)
    return target_path.name


def poll_training_task(task_id, token):
    last_data = None
    for _ in range(50):
        payload = request(f"/models/train/tasks/{task_id}", token=token)
        last_data = payload["data"]
        if last_data.get("status") in {"completed", "failed"}:
            return last_data
        time.sleep(5)
    raise CheckFailure(f"Training task timeout: {task_id}")


def cleanup_model_artifacts(model_name):
    stem = Path(model_name).stem
    for path in (
        ROOT / f"plantbackend/models/{model_name}",
        ROOT / f"plantbackend/models/{stem}.labels.json",
        ROOT / f"plantbackend/models/{stem}.meta.json",
        ROOT / f"plantbackend/training_runs/{stem}_run",
    ):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM model_ownership WHERE model_name = ?", (model_name,))
        conn.commit()


def ensure_zip_bytes(body):
    assert_true(body[:2] == b"PK", "Expected ZIP response body")


def main():
    assert_true(SOURCE_MODEL.exists(), f"Missing source model: {SOURCE_MODEL}")

    cleanup_actions = []
    tmpdir = Path(tempfile.mkdtemp(prefix="full_feature_check_"))
    source_dataset_zip = tmpdir / "generated_smoke_dataset.zip"
    generated_dataset_name = build_sample_dataset_zip(source_dataset_zip)
    admin_token = None
    user_token = None
    third_token = None
    temp_user_token = None
    temp_username = ""
    temp_password = "temp1234"
    temp_user_id = None
    sample_source_name = ""

    try:
        log("1. Health")
        health = request("/health")
        assert_true(health.get("success") is True, "Health failed")

        log("2. Login")
        admin_token, _ = login(ADMIN_USERNAME, ADMIN_PASSWORD)
        user_token, _ = login(USER_USERNAME, USER_PASSWORD)
        third_token, _ = try_login(THIRD_USERNAME, THIRD_PASSWORD)

        log("3. Session and admin views")
        session_payload = request("/auth/session", token=admin_token)
        assert_true(session_payload.get("data", {}).get("user", {}).get("role") == "admin", "Admin session invalid")
        users_payload = request("/users", token=admin_token)
        assert_true(len(users_payload.get("data", {}).get("users", [])) >= 2, "User list too short")
        admin_console = request("/admin/console", token=admin_token)
        assert_true(admin_console.get("success") is True, "Admin console failed")
        request("/admin/augmentations/select", method="POST", token=admin_token, expected_status=200, parse_json=True)

        log("4. Temp user registration")
        temp_username = f"user_{int(time.time())}_{uuid.uuid4().hex[:4]}"
        temp_user_token, _ = register_user(temp_username, temp_password, display_name="回归用户")
        cleanup_actions.append(("user", temp_username))
        users_payload = request("/users", token=admin_token)
        temp_user = find_user(users_payload, temp_username)
        assert_true(temp_user is not None, "Temp user missing from admin user list")
        temp_user_id = int(temp_user["id"])

        log("5. Models and AI recommendation")
        admin_models = request("/models", token=admin_token)
        user_models = request("/models", token=user_token)
        assert_true(admin_models["data"]["available_models"], "No models visible to admin")
        assert_true(user_models["data"]["available_models"], "No models visible to user")
        ai_payload = request(
            "/ai/recommendation",
            method="POST",
            json_payload={"disease_label": "No detection", "confidence": 0.0, "top_predictions": []},
        )
        assert_true(ai_payload.get("success") is True, "AI recommendation failed")

        log("6. User model upload visibility, official labels, admin user actions")
        temp_private_model_name = f"{temp_username}_private.onnx"
        request(
            "/models/upload",
            method="POST",
            token=temp_user_token,
            multipart_fields={"activate": "false", "is_public": "false"},
            multipart_files={
                "model_file": {
                    "filename": temp_private_model_name,
                    "content": SOURCE_MODEL.read_bytes(),
                    "content_type": "application/octet-stream",
                }
            },
        )
        cleanup_actions.append(("model", temp_private_model_name))
        temp_public_model_name = f"{temp_username}_public.onnx"
        request(
            "/models/upload",
            method="POST",
            token=temp_user_token,
            multipart_fields={"activate": "false", "is_public": "true"},
            multipart_files={
                "model_file": {
                    "filename": temp_public_model_name,
                    "content": SOURCE_MODEL.read_bytes(),
                    "content_type": "application/octet-stream",
                }
            },
        )
        cleanup_actions.append(("model", temp_public_model_name))

        temp_user_models = request("/models", token=temp_user_token)
        private_item = find_model_item(temp_user_models, temp_private_model_name)
        assert_true(private_item is not None, "Temp user private model missing")
        assert_true(private_item.get("is_public") is False, "Private model should not be public")
        assert_true(private_item.get("is_official") is False, "User model should not be official")
        assert_true(private_item.get("can_manage") is True, "Owner should be able to manage private model")

        other_user_models = request("/models", token=user_token)
        assert_true(
            temp_private_model_name not in other_user_models["data"]["available_models"],
            "Other users should not see temp user's private model",
        )
        public_item = find_model_item(other_user_models, temp_public_model_name)
        assert_true(public_item is not None, "Other users should see temp user's public model")
        assert_true(public_item.get("is_public") is True, "Public model should be marked public")
        assert_true(public_item.get("can_manage") is False, "Other users should not manage temp user's public model")

        official_model_name = f"official_smoke_{int(time.time())}.onnx"
        request(
            "/admin/models/upload",
            method="POST",
            token=admin_token,
            multipart_fields={"activate": "false", "is_public": "true"},
            multipart_files={
                "model_file": {
                    "filename": official_model_name,
                    "content": SOURCE_MODEL.read_bytes(),
                    "content_type": "application/octet-stream",
                }
            },
        )
        cleanup_actions.append(("model", official_model_name))
        other_user_models = request("/models", token=user_token)
        official_item = find_model_item(other_user_models, official_model_name)
        assert_true(official_item is not None, "Official model missing from user model list")
        assert_true(official_item.get("is_official") is True, "Admin uploaded model should be marked official")
        assert_true(official_item.get("is_public") is True, "Official model should be public in this test")

        admin_console = request("/admin/console", token=admin_token)
        managed_model_names = [item["name"] for item in admin_console["data"]["managed_models"]]
        assert_true(temp_private_model_name in managed_model_names, "Admin console missing user private model")
        assert_true(temp_public_model_name in managed_model_names, "Admin console missing user public model")
        assert_true(official_model_name in managed_model_names, "Admin console missing official model")

        request(
            "/models/delete",
            method="POST",
            token=admin_token,
            json_payload={"model_name": temp_public_model_name},
        )
        other_user_models = request("/models", token=user_token)
        assert_true(
            temp_public_model_name not in other_user_models["data"]["available_models"],
            "Admin model delete should remove user public model from other users",
        )

        flagged_users = request(
            f"/admin/users/{temp_user_id}/flagged",
            method="POST",
            token=admin_token,
            json_payload={"value": True},
        )
        temp_user = find_user(flagged_users, temp_username)
        assert_true(temp_user and temp_user.get("is_flagged") is True, "Admin flag user failed")

        disabled_users = request(
            f"/admin/users/{temp_user_id}/disabled",
            method="POST",
            token=admin_token,
            json_payload={"value": True},
        )
        temp_user = find_user(disabled_users, temp_username)
        assert_true(temp_user and temp_user.get("is_disabled") is True, "Admin disable user failed")
        request("/auth/session", token=temp_user_token, expected_status=401)
        banned_login = request(
            "/auth/login",
            method="POST",
            json_payload={"username": temp_username, "password": temp_password},
            expected_status=400,
        )
        assert_true("封禁" in str(banned_login.get("detail") or ""), "Disabled user should receive ban message")

        enabled_users = request(
            f"/admin/users/{temp_user_id}/disabled",
            method="POST",
            token=admin_token,
            json_payload={"value": False},
        )
        temp_user = find_user(enabled_users, temp_username)
        assert_true(temp_user and temp_user.get("is_disabled") is False, "Admin enable user failed")
        temp_user_token, _ = login(temp_username, temp_password)

        admin_delete_dataset = f"{temp_username}_admin_delete"
        admin_delete_dataset_dir = ROOT / f"plantbackend/annotation_datasets/{admin_delete_dataset}"
        request(
            "/annotation/datasets",
            method="POST",
            token=temp_user_token,
            json_payload={"dataset_name": admin_delete_dataset, "is_public": False},
        )
        cleanup_actions.append(("dataset_temp", admin_delete_dataset))
        assert_true(admin_delete_dataset_dir.exists(), "Temp dataset for admin delete was not created")
        request(
            "/annotation/datasets/delete",
            method="POST",
            token=admin_token,
            json_payload={"dataset_name": admin_delete_dataset},
        )
        assert_true(not admin_delete_dataset_dir.exists(), "Admin should be able to delete user dataset")

        user_cleanup_dataset = f"{temp_username}_cleanup"
        user_cleanup_dataset_dir = ROOT / f"plantbackend/annotation_datasets/{user_cleanup_dataset}"
        request(
            "/annotation/datasets",
            method="POST",
            token=temp_user_token,
            json_payload={"dataset_name": user_cleanup_dataset, "is_public": False},
        )
        cleanup_actions.append(("dataset_temp", user_cleanup_dataset))
        assert_true(user_cleanup_dataset_dir.exists(), "Temp cleanup dataset was not created")

        deleted_users = request(
            f"/admin/users/{temp_user_id}",
            method="DELETE",
            token=admin_token,
        )
        assert_true(find_user(deleted_users, temp_username) is None, "Deleted user still present in admin list")
        assert_true(not user_cleanup_dataset_dir.exists(), "Deleting user should remove owned dataset directory")
        assert_true(
            not (ROOT / f"plantbackend/models/{temp_private_model_name}").exists(),
            "Deleting user should remove owned private model",
        )
        request(
            "/auth/login",
            method="POST",
            json_payload={"username": temp_username, "password": temp_password},
            expected_status=401,
        )

        log("7. Admin model upload/download")
        upload_model_name = f"upload_smoke_{int(time.time())}.onnx"
        upload_model_path = tmpdir / upload_model_name
        upload_model_path.write_bytes(SOURCE_MODEL.read_bytes())
        upload_payload = request(
            "/admin/models/upload",
            method="POST",
            token=admin_token,
            multipart_fields={"activate": "false", "is_public": "true"},
            multipart_files={
                "model_file": {
                    "filename": upload_model_name,
                    "content": upload_model_path.read_bytes(),
                    "content_type": "application/octet-stream",
                }
            },
        )
        cleanup_actions.append(("model", upload_model_name))
        managed_names = [item["name"] for item in upload_payload["data"]["managed_models"]]
        assert_true(upload_model_name in managed_names, "Uploaded model not present in admin console")
        body, _ = request(f"/models/{urllib.parse.quote(upload_model_name)}/download", token=admin_token, parse_json=False)
        ensure_zip_bytes(body)

        log("8. User private dataset CRUD, annotation, download, augment")
        user_dataset = f"{USER_USERNAME}_full_check_{int(time.time())}"
        request(
            "/annotation/datasets",
            method="POST",
            token=user_token,
            json_payload={"dataset_name": user_dataset, "is_public": False},
        )
        cleanup_actions.append(("dataset_user", user_dataset))

        request(
            "/annotation/classes",
            method="POST",
            token=user_token,
            json_payload={"dataset_name": user_dataset, "class_name": "smoke_leaf"},
        )
        request(
            "/annotation/classes",
            method="POST",
            token=user_token,
            json_payload={"dataset_name": user_dataset, "class_name": "temp_delete"},
        )
        request(
            "/annotation/classes/delete",
            method="POST",
            token=user_token,
            json_payload={"dataset_name": user_dataset, "class_name": "temp_delete"},
        )

        sample_small = tmpdir / "user_dataset_sample.bmp"
        sample_source_name = write_sample_image(sample_small)
        annotation_payload = json.dumps(
            [{"label": "smoke_leaf", "x1": 12, "y1": 18, "x2": 92, "y2": 96, "source": "manual"}],
            ensure_ascii=False,
        )
        save_resp = request(
            "/annotation/save",
            method="POST",
            token=user_token,
            multipart_fields={"annotations": annotation_payload, "dataset_name": user_dataset},
            multipart_files={
                "file": {
                    "filename": sample_small.name,
                    "content": sample_small.read_bytes(),
                    "content_type": "image/jpeg",
                }
            },
        )
        assert_true(save_resp["data"]["dataset_name"] == user_dataset, "Annotation save returned wrong dataset")

        user_classes = request("/annotation/classes", token=user_token)
        assert_true(user_dataset in user_classes["data"]["available_datasets"], "User dataset missing from user view")
        request(f"/annotation/classes?{urllib.parse.urlencode({'dataset': user_dataset})}", token=user_token)
        request(f"/annotation/classes?{urllib.parse.urlencode({'dataset': user_dataset})}", token=admin_token)
        if third_token:
            request(
                f"/annotation/classes?{urllib.parse.urlencode({'dataset': user_dataset})}",
                token=third_token,
                expected_status=404,
            )
        body, _ = request(
            f"/annotation/datasets/{urllib.parse.quote(user_dataset)}/download",
            token=user_token,
            parse_json=False,
        )
        ensure_zip_bytes(body)
        request(
            "/annotation/augment",
            method="POST",
            token=user_token,
            json_payload={"dataset_name": user_dataset, "copies": 1, "train_ratio": 0.8, "seed": 1},
        )

        log("9. Admin dataset upload, training, metrics, predict, model download")
        train_dataset = f"full_train_{int(time.time())}"
        request(
            "/admin/datasets/upload",
            method="POST",
            token=admin_token,
            multipart_fields={"dataset_name": train_dataset, "is_public": "false"},
            multipart_files={
                "dataset_file": {
                    "filename": generated_dataset_name,
                    "content": source_dataset_zip.read_bytes(),
                    "content_type": "application/zip",
                }
            },
        )
        cleanup_actions.append(("dataset_admin", train_dataset))

        train_model_name = f"{train_dataset}.onnx"
        start_payload = request(
            "/models/train/tasks",
            method="POST",
            token=admin_token,
            json_payload={
                "dataset_name": train_dataset,
                "base_model": "yolov8n.pt",
                "model_name": train_model_name,
                "epochs": 1,
                "imgsz": 64,
            },
        )
        cleanup_actions.append(("model", train_model_name))
        task_id = start_payload["data"]["task_id"]
        task_data = poll_training_task(task_id, admin_token)
        assert_true(task_data["status"] == "completed", f"Training did not complete: {task_data}")
        result = task_data.get("result") or {}
        assert_true(result.get("map50") is not None, "Training result missing map50")
        assert_true(result.get("training_summary"), "Training result missing summary")
        assert_true(result.get("training_advice"), "Training result missing advice")

        body, _ = request(f"/models/{urllib.parse.quote(train_model_name)}/download", token=admin_token, parse_json=False)
        ensure_zip_bytes(body)

        predict_image = tmpdir / "predict_sample.bmp"
        write_sample_image(predict_image)
        predict_payload = request(
            f"/predict?{urllib.parse.urlencode({'model_name': train_model_name})}",
            method="POST",
            token=admin_token,
            multipart_files={
                "file": {
                    "filename": predict_image.name,
                    "content": predict_image.read_bytes(),
                    "content_type": "image/jpeg",
                }
            },
        )
        assert_true(predict_payload.get("success") is True, "Predict failed for trained model")

        post_train_models = request("/models", token=user_token)
        assert_true(train_model_name in post_train_models["data"]["available_models"], "Trained model not visible after training")
        request(f"/models/select?{urllib.parse.urlencode({'model_name': 'best.onnx'})}", method="POST", token=admin_token)

        log("Full feature check passed.")
        log(f"Sample image used: {sample_source_name}")
    finally:
        for kind, name in reversed(cleanup_actions):
            try:
                if kind == "dataset_user":
                    request(
                        "/annotation/datasets/delete",
                        method="POST",
                        token=user_token,
                        json_payload={"dataset_name": name},
                    )
                elif kind == "dataset_admin":
                    request(
                        "/annotation/datasets/delete",
                        method="POST",
                        token=admin_token,
                        json_payload={"dataset_name": name},
                    )
                elif kind == "dataset_temp":
                    request(
                        "/annotation/datasets/delete",
                        method="POST",
                        token=admin_token,
                        json_payload={"dataset_name": name},
                    )
                elif kind == "model":
                    cleanup_model_artifacts(name)
                elif kind == "user" and admin_token:
                    users_payload = request("/users", token=admin_token)
                    temp_user = find_user(users_payload, name)
                    if temp_user:
                        request(
                            f"/admin/users/{int(temp_user['id'])}",
                            method="DELETE",
                            token=admin_token,
                        )
            except Exception:
                pass
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Full feature check failed: {exc}", file=sys.stderr)
        sys.exit(1)
