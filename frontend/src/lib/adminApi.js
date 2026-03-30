import { requestApi } from "@/lib/api";

export async function fetchAdminConsole(token, signal) {
  return requestApi("/admin/console", { token, signal });
}

export async function fetchUsers(token, signal) {
  return requestApi("/users", { token, signal });
}

export async function setUserDisabled(token, userId, value) {
  return requestApi(`/admin/users/${encodeURIComponent(userId)}/disabled`, {
    method: "POST",
    token,
    body: { value: Boolean(value) },
  });
}

export async function setUserFlagged(token, userId, value) {
  return requestApi(`/admin/users/${encodeURIComponent(userId)}/flagged`, {
    method: "POST",
    token,
    body: { value: Boolean(value) },
  });
}

export {
  deleteUserAccount,
  selectAdminAugmentation,
  uploadAdminAugmentation,
  uploadAdminDataset,
  uploadAdminModel,
} from "@/lib/legacyAdminApi";