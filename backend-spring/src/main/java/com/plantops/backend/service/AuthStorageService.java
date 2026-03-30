package com.plantops.backend.service;

import com.plantops.backend.config.PlantStorageProperties;
import com.plantops.backend.model.DomainTypes;
import com.plantops.backend.web.PlantApiException;
import jakarta.annotation.PostConstruct;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.security.spec.KeySpec;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.ResultSetMetaData;
import java.sql.SQLException;
import java.sql.Statement;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;
import java.util.Locale;
import java.util.Objects;
import java.util.regex.Pattern;
import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.PBEKeySpec;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

@Service
public class AuthStorageService {

    private static final Pattern USERNAME_SANITIZER = Pattern.compile("[^A-Za-z0-9_-]+");
    private static final Pattern UNDERSCORE_COLLAPSE = Pattern.compile("_+");
    private static final int PASSWORD_ITERATIONS = 120_000;
    private static final String SESSION_TOKEN_PREFIX = "sha256";

    private final PlantStorageProperties properties;
    private final SecureRandom secureRandom = new SecureRandom();

    public AuthStorageService(PlantStorageProperties properties) {
        this.properties = properties;
    }

    @PostConstruct
    public void initialize() {
        try {
            Files.createDirectories(properties.resolveAuthDbPath().getParent());
            initializeSchema();
            seedDefaultUsers();
        } catch (SQLException exception) {
            throw new IllegalStateException("Failed to initialize the shared auth store", exception);
        } catch (Exception exception) {
            throw new IllegalStateException("Failed to initialize the shared auth store", exception);
        }
    }

    public DomainTypes.AppUser getUserByUsername(String username) {
        String safeUsername = normalizeUsername(username);
        try (Connection connection = connect();
             PreparedStatement statement = connection.prepareStatement(
                 "SELECT id, username, display_name, role, is_disabled, is_flagged, created_at FROM users WHERE username = ?"
             )) {
            statement.setString(1, safeUsername);
            try (ResultSet resultSet = statement.executeQuery()) {
                return resultSet.next() ? rowToUser(resultSet) : null;
            }
        } catch (SQLException exception) {
            throw new IllegalStateException("Failed to query user by username", exception);
        }
    }

    public DomainTypes.AppUser getUserById(int userId) {
        try (Connection connection = connect();
             PreparedStatement statement = connection.prepareStatement(
                 "SELECT id, username, display_name, role, is_disabled, is_flagged, created_at FROM users WHERE id = ?"
             )) {
            statement.setInt(1, userId);
            try (ResultSet resultSet = statement.executeQuery()) {
                return resultSet.next() ? rowToUser(resultSet) : null;
            }
        } catch (SQLException exception) {
            throw new IllegalStateException("Failed to query user by id", exception);
        }
    }

    public DomainTypes.AppUser getPrimaryAdminUser() {
        try (Connection connection = connect();
             PreparedStatement statement = connection.prepareStatement(
                 """
                 SELECT id, username, display_name, role, is_disabled, is_flagged, created_at
                 FROM users
                 WHERE role = 'admin'
                 ORDER BY id
                 LIMIT 1
                 """
             );
             ResultSet resultSet = statement.executeQuery()) {
            return resultSet.next() ? rowToUser(resultSet) : null;
        } catch (SQLException exception) {
            throw new IllegalStateException("Failed to query primary admin", exception);
        }
    }

    public DomainTypes.AppUser createUser(
        String username,
        String password,
        String role,
        String displayName,
        boolean allowExisting
    ) {
        String safeUsername = normalizeUsername(username);
        if ((password == null ? "" : password).length() < 4) {
            throw new PlantApiException(HttpStatus.BAD_REQUEST, "密码至少需要 4 个字符");
        }

        DomainTypes.AppUser existing = getUserByUsername(safeUsername);
        if (existing != null) {
            if (allowExisting) {
                return existing;
            }
            throw new PlantApiException(HttpStatus.BAD_REQUEST, "用户名已存在：" + safeUsername);
        }

        String safeRole = "admin".equals(role) ? "admin" : "user";
        String safeDisplayName = normalizeDisplayName(displayName, safeUsername);
        String passwordHash = hashPassword(password, null);

        try (Connection connection = connect();
             PreparedStatement statement = connection.prepareStatement(
                 """
                 INSERT INTO users (username, display_name, password_hash, role, is_disabled, is_flagged, created_at)
                 VALUES (?, ?, ?, ?, 0, 0, ?)
                 """,
                 Statement.RETURN_GENERATED_KEYS
             )) {
            statement.setString(1, safeUsername);
            statement.setString(2, safeDisplayName);
            statement.setString(3, passwordHash);
            statement.setString(4, safeRole);
            statement.setString(5, utcTimestamp());
            statement.executeUpdate();
            try (ResultSet generatedKeys = statement.getGeneratedKeys()) {
                if (!generatedKeys.next()) {
                    throw new IllegalStateException("User creation did not return a generated key");
                }
                DomainTypes.AppUser created = getUserById(generatedKeys.getInt(1));
                if (created == null) {
                    throw new IllegalStateException("User creation finished but the record is missing");
                }
                return created;
            }
        } catch (SQLException exception) {
            throw new IllegalStateException("Failed to create user", exception);
        }
    }

    public DomainTypes.AppUser authenticateUser(String username, String password) {
        String safeUsername = normalizeUsername(username);
        try (Connection connection = connect();
             PreparedStatement statement = connection.prepareStatement(
                 """
                 SELECT id, username, display_name, password_hash, role, is_disabled, is_flagged, created_at
                 FROM users
                 WHERE username = ?
                 """
             )) {
            statement.setString(1, safeUsername);
            try (ResultSet resultSet = statement.executeQuery()) {
                if (!resultSet.next()) {
                    return null;
                }
                if (!verifyPassword(password, resultSet.getString("password_hash"))) {
                    return null;
                }
                if (resultSet.getBoolean("is_disabled")) {
                    throw new PlantApiException(HttpStatus.BAD_REQUEST, "该账号已被管理员封禁，请联系管理员");
                }
                return rowToUser(resultSet);
            }
        } catch (SQLException exception) {
            throw new IllegalStateException("Failed to authenticate user", exception);
        }
    }

    public String createSession(int userId) {
        String token = generateSessionToken();
        String tokenHash = hashSessionToken(token);
        OffsetDateTime createdAt = utcNow();
        OffsetDateTime expiresAt = createdAt.plusHours(Math.max(1, properties.getAuthSessionHours()));
        try (Connection connection = connect();
             PreparedStatement statement = connection.prepareStatement(
                 """
                 INSERT INTO sessions (token, user_id, created_at, expires_at)
                 VALUES (?, ?, ?, ?)
                 """
             )) {
            statement.setString(1, tokenHash);
            statement.setInt(2, userId);
            statement.setString(3, createdAt.toString());
            statement.setString(4, expiresAt.toString());
            statement.executeUpdate();
            return token;
        } catch (SQLException exception) {
            throw new IllegalStateException("Failed to create session", exception);
        }
    }
    public void deleteSession(String token) {
        String safeToken = token == null ? "" : token.trim();
        String tokenHash = hashSessionToken(safeToken);
        try (Connection connection = connect();
             PreparedStatement statement = connection.prepareStatement(
                 "DELETE FROM sessions WHERE token IN (?, ?)"
             )) {
            statement.setString(1, safeToken);
            statement.setString(2, tokenHash);
            statement.executeUpdate();
        } catch (SQLException exception) {
            throw new IllegalStateException("Failed to delete session", exception);
        }
    }

    public void deleteSessionsForUser(int userId) {
        try (Connection connection = connect();
             PreparedStatement statement = connection.prepareStatement("DELETE FROM sessions WHERE user_id = ?")) {
            statement.setInt(1, userId);
            statement.executeUpdate();
        } catch (SQLException exception) {
            throw new IllegalStateException("Failed to delete sessions for user", exception);
        }
    }

    public DomainTypes.AppUser getUserByToken(String token) {
        String safeToken = token == null ? "" : token.trim();
        if (safeToken.isEmpty()) {
            return null;
        }
        String tokenHash = hashSessionToken(safeToken);

        try (Connection connection = connect();
             PreparedStatement statement = connection.prepareStatement(
                 """
                 SELECT
                     users.id,
                     users.username,
                     users.display_name,
                     users.role,
                     users.is_disabled,
                     users.is_flagged,
                     users.created_at,
                     sessions.token AS session_token,
                     sessions.expires_at
                 FROM sessions
                 JOIN users ON users.id = sessions.user_id
                 WHERE sessions.token IN (?, ?)
                 """
             )) {
            statement.setString(1, safeToken);
            statement.setString(2, tokenHash);
            try (ResultSet resultSet = statement.executeQuery()) {
                if (!resultSet.next()) {
                    return null;
                }

                String sessionToken = resultSet.getString("session_token");
                OffsetDateTime expiresAt;
                try {
                    expiresAt = OffsetDateTime.parse(resultSet.getString("expires_at"));
                } catch (Exception exception) {
                    deleteExactSessionToken(sessionToken);
                    return null;
                }

                if (!expiresAt.isAfter(utcNow())) {
                    deleteExactSessionToken(sessionToken);
                    return null;
                }

                DomainTypes.AppUser user = rowToUser(resultSet);
                if (user.disabled()) {
                    deleteSessionsForUser(user.id());
                    return null;
                }

                if (Objects.equals(sessionToken, safeToken)) {
                    migratePlainSessionToken(safeToken, tokenHash);
                }
                return user;
            }
        } catch (SQLException exception) {
            throw new IllegalStateException("Failed to query user by token", exception);
        }
    }

    public void ensureDatasetAccessEntry(String datasetName, int ownerUserId, boolean isPublic, boolean overwriteExisting) {
        String sql = overwriteExisting
            ? """
              INSERT INTO dataset_ownership (dataset_name, owner_user_id, is_public, created_at)
              VALUES (?, ?, ?, ?)
              ON CONFLICT(dataset_name) DO UPDATE SET
                  owner_user_id = excluded.owner_user_id,
                  is_public = excluded.is_public
              """
            : """
              INSERT OR IGNORE INTO dataset_ownership (dataset_name, owner_user_id, is_public, created_at)
              VALUES (?, ?, ?, ?)
              """;
        try (Connection connection = connect();
             PreparedStatement statement = connection.prepareStatement(sql)) {
            statement.setString(1, datasetName);
            statement.setInt(2, ownerUserId);
            statement.setInt(3, isPublic ? 1 : 0);
            statement.setString(4, utcTimestamp());
            statement.executeUpdate();
        } catch (SQLException exception) {
            throw new IllegalStateException("Failed to upsert dataset ownership", exception);
        }
    }

    public DomainTypes.DatasetOwnership getDatasetOwner(String datasetName) {
        try (Connection connection = connect();
             PreparedStatement statement = connection.prepareStatement(
                 """
                 SELECT
                     dataset_ownership.dataset_name,
                     dataset_ownership.owner_user_id,
                     dataset_ownership.is_public,
                     dataset_ownership.created_at,
                     users.username AS owner_username,
                     users.display_name AS owner_display_name,
                     users.role AS owner_role
                 FROM dataset_ownership
                 JOIN users ON users.id = dataset_ownership.owner_user_id
                 WHERE dataset_ownership.dataset_name = ?
                 """
             )) {
            statement.setString(1, datasetName);
            try (ResultSet resultSet = statement.executeQuery()) {
                return resultSet.next() ? rowToDatasetOwnership(resultSet) : null;
            }
        } catch (SQLException exception) {
            throw new IllegalStateException("Failed to query dataset ownership", exception);
        }
    }

    public List<DomainTypes.DatasetOwnership> listAllDatasets() {
        try (Connection connection = connect();
             PreparedStatement statement = connection.prepareStatement(
                 """
                 SELECT
                     dataset_ownership.dataset_name,
                     dataset_ownership.owner_user_id,
                     dataset_ownership.is_public,
                     dataset_ownership.created_at,
                     users.username AS owner_username,
                     users.display_name AS owner_display_name,
                     users.role AS owner_role
                 FROM dataset_ownership
                 JOIN users ON users.id = dataset_ownership.owner_user_id
                 ORDER BY dataset_ownership.dataset_name
                 """
             );
             ResultSet resultSet = statement.executeQuery()) {
            List<DomainTypes.DatasetOwnership> items = new ArrayList<>();
            while (resultSet.next()) {
                items.add(rowToDatasetOwnership(resultSet));
            }
            return items;
        } catch (SQLException exception) {
            throw new IllegalStateException("Failed to list datasets", exception);
        }
    }

    public List<DomainTypes.DatasetOwnership> listDatasetsOwnedByUser(int userId) {
        try (Connection connection = connect();
             PreparedStatement statement = connection.prepareStatement(
                 """
                 SELECT dataset_name, owner_user_id, is_public, created_at
                 FROM dataset_ownership
                 WHERE owner_user_id = ?
                 ORDER BY dataset_name
                 """
             )) {
            statement.setInt(1, userId);
            try (ResultSet resultSet = statement.executeQuery()) {
                List<DomainTypes.DatasetOwnership> items = new ArrayList<>();
                while (resultSet.next()) {
                    items.add(new DomainTypes.DatasetOwnership(
                        resultSet.getString("dataset_name"),
                        resultSet.getInt("owner_user_id"),
                        resultSet.getBoolean("is_public"),
                        resultSet.getString("created_at"),
                        null,
                        null,
                        null
                    ));
                }
                return items;
            }
        } catch (SQLException exception) {
            throw new IllegalStateException("Failed to list datasets owned by user", exception);
        }
    }

    public void deleteDatasetOwner(String datasetName) {
        try (Connection connection = connect()) {
            try (PreparedStatement deleteOwnership = connection.prepareStatement(
                "DELETE FROM dataset_ownership WHERE dataset_name = ?"
            )) {
                deleteOwnership.setString(1, datasetName);
                deleteOwnership.executeUpdate();
            }
            try (PreparedStatement deleteAdvice = connection.prepareStatement(
                "DELETE FROM class_advice_cache WHERE dataset_name = ?"
            )) {
                deleteAdvice.setString(1, datasetName);
                deleteAdvice.executeUpdate();
            }
        } catch (SQLException exception) {
            throw new IllegalStateException("Failed to delete dataset ownership", exception);
        }
    }
    public void ensureModelOwner(String modelName, int ownerUserId, boolean isPublic, boolean overwriteExisting) {
        String sql = overwriteExisting
            ? """
              INSERT INTO model_ownership (model_name, owner_user_id, is_public, created_at)
              VALUES (?, ?, ?, ?)
              ON CONFLICT(model_name) DO UPDATE SET
                  owner_user_id = excluded.owner_user_id,
                  is_public = excluded.is_public
              """
            : """
              INSERT OR IGNORE INTO model_ownership (model_name, owner_user_id, is_public, created_at)
              VALUES (?, ?, ?, ?)
              """;
        try (Connection connection = connect();
             PreparedStatement statement = connection.prepareStatement(sql)) {
            statement.setString(1, modelName);
            statement.setInt(2, ownerUserId);
            statement.setInt(3, isPublic ? 1 : 0);
            statement.setString(4, utcTimestamp());
            statement.executeUpdate();
        } catch (SQLException exception) {
            throw new IllegalStateException("Failed to upsert model ownership", exception);
        }
    }

    public DomainTypes.ModelOwnership getModelOwner(String modelName) {
        try (Connection connection = connect();
             PreparedStatement statement = connection.prepareStatement(
                 """
                 SELECT
                     model_ownership.model_name,
                     model_ownership.owner_user_id,
                     model_ownership.is_public,
                     model_ownership.created_at,
                     users.username AS owner_username,
                     users.display_name AS owner_display_name,
                     users.role AS owner_role
                 FROM model_ownership
                 JOIN users ON users.id = model_ownership.owner_user_id
                 WHERE model_ownership.model_name = ?
                 """
             )) {
            statement.setString(1, modelName);
            try (ResultSet resultSet = statement.executeQuery()) {
                return resultSet.next() ? rowToModelOwnership(resultSet) : null;
            }
        } catch (SQLException exception) {
            throw new IllegalStateException("Failed to query model ownership", exception);
        }
    }

    public List<DomainTypes.ModelOwnership> listAccessibleModelsForUser(int userId) {
        try (Connection connection = connect();
             PreparedStatement statement = connection.prepareStatement(
                 """
                 SELECT
                     model_ownership.model_name,
                     model_ownership.owner_user_id,
                     model_ownership.is_public,
                     model_ownership.created_at,
                     users.username AS owner_username,
                     users.display_name AS owner_display_name,
                     users.role AS owner_role
                 FROM model_ownership
                 JOIN users ON users.id = model_ownership.owner_user_id
                 WHERE model_ownership.owner_user_id = ? OR model_ownership.is_public = 1
                 ORDER BY model_ownership.model_name
                 """
             )) {
            statement.setInt(1, userId);
            try (ResultSet resultSet = statement.executeQuery()) {
                List<DomainTypes.ModelOwnership> items = new ArrayList<>();
                while (resultSet.next()) {
                    items.add(rowToModelOwnership(resultSet));
                }
                return items;
            }
        } catch (SQLException exception) {
            throw new IllegalStateException("Failed to list accessible models", exception);
        }
    }

    public List<String> listAccessibleModelNamesForUser(int userId) {
        return listAccessibleModelsForUser(userId).stream().map(DomainTypes.ModelOwnership::modelName).toList();
    }

    public List<DomainTypes.ModelOwnership> listAllModels() {
        try (Connection connection = connect();
             PreparedStatement statement = connection.prepareStatement(
                 """
                 SELECT
                     model_ownership.model_name,
                     model_ownership.owner_user_id,
                     model_ownership.is_public,
                     model_ownership.created_at,
                     users.username AS owner_username,
                     users.display_name AS owner_display_name,
                     users.role AS owner_role
                 FROM model_ownership
                 JOIN users ON users.id = model_ownership.owner_user_id
                 ORDER BY model_ownership.model_name
                 """
             );
             ResultSet resultSet = statement.executeQuery()) {
            List<DomainTypes.ModelOwnership> items = new ArrayList<>();
            while (resultSet.next()) {
                items.add(rowToModelOwnership(resultSet));
            }
            return items;
        } catch (SQLException exception) {
            throw new IllegalStateException("Failed to list models", exception);
        }
    }

    public List<DomainTypes.ModelOwnership> listModelsOwnedByUser(int userId) {
        try (Connection connection = connect();
             PreparedStatement statement = connection.prepareStatement(
                 """
                 SELECT model_name, owner_user_id, is_public, created_at
                 FROM model_ownership
                 WHERE owner_user_id = ?
                 ORDER BY model_name
                 """
             )) {
            statement.setInt(1, userId);
            try (ResultSet resultSet = statement.executeQuery()) {
                List<DomainTypes.ModelOwnership> items = new ArrayList<>();
                while (resultSet.next()) {
                    items.add(new DomainTypes.ModelOwnership(
                        resultSet.getString("model_name"),
                        resultSet.getInt("owner_user_id"),
                        resultSet.getBoolean("is_public"),
                        resultSet.getString("created_at"),
                        null,
                        null,
                        null
                    ));
                }
                return items;
            }
        } catch (SQLException exception) {
            throw new IllegalStateException("Failed to list models owned by user", exception);
        }
    }

    public void deleteModelOwner(String modelName) {
        try (Connection connection = connect();
             PreparedStatement statement = connection.prepareStatement("DELETE FROM model_ownership WHERE model_name = ?")) {
            statement.setString(1, modelName);
            statement.executeUpdate();
        } catch (SQLException exception) {
            throw new IllegalStateException("Failed to delete model ownership", exception);
        }
    }

    public DomainTypes.AppUser setUserDisabled(int userId, boolean isDisabled) {
        try (Connection connection = connect();
             PreparedStatement statement = connection.prepareStatement("UPDATE users SET is_disabled = ? WHERE id = ?")) {
            statement.setInt(1, isDisabled ? 1 : 0);
            statement.setInt(2, userId);
            statement.executeUpdate();
        } catch (SQLException exception) {
            throw new IllegalStateException("Failed to update disabled flag", exception);
        }
        if (isDisabled) {
            deleteSessionsForUser(userId);
        }
        return getUserById(userId);
    }

    public DomainTypes.AppUser setUserFlagged(int userId, boolean isFlagged) {
        try (Connection connection = connect();
             PreparedStatement statement = connection.prepareStatement("UPDATE users SET is_flagged = ? WHERE id = ?")) {
            statement.setInt(1, isFlagged ? 1 : 0);
            statement.setInt(2, userId);
            statement.executeUpdate();
            return getUserById(userId);
        } catch (SQLException exception) {
            throw new IllegalStateException("Failed to update flagged state", exception);
        }
    }

    public void deleteUser(int userId) {
        try (Connection connection = connect();
             PreparedStatement statement = connection.prepareStatement("DELETE FROM users WHERE id = ?")) {
            statement.setInt(1, userId);
            statement.executeUpdate();
        } catch (SQLException exception) {
            throw new IllegalStateException("Failed to delete user", exception);
        }
    }

    public List<DomainTypes.AppUser> listUsers() {
        try (Connection connection = connect();
             PreparedStatement statement = connection.prepareStatement(
                 """
                 SELECT
                     users.id,
                     users.username,
                     users.display_name,
                     users.role,
                     users.is_disabled,
                     users.is_flagged,
                     users.created_at,
                     COUNT(DISTINCT dataset_ownership.dataset_name) AS dataset_count,
                     COUNT(DISTINCT model_ownership.model_name) AS model_count
                 FROM users
                 LEFT JOIN dataset_ownership ON dataset_ownership.owner_user_id = users.id
                 LEFT JOIN model_ownership ON model_ownership.owner_user_id = users.id
                 GROUP BY users.id
                 ORDER BY CASE WHEN users.role = 'admin' THEN 0 ELSE 1 END, users.username
                 """
             );
             ResultSet resultSet = statement.executeQuery()) {
            List<DomainTypes.AppUser> users = new ArrayList<>();
            while (resultSet.next()) {
                users.add(rowToUser(resultSet));
            }
            return users;
        } catch (SQLException exception) {
            throw new IllegalStateException("Failed to list users", exception);
        }
    }

    public int countDatasetsForUser(DomainTypes.AppUser user) {
        String role = user == null ? "" : user.role();
        try (Connection connection = connect()) {
            if ("admin".equals(role)) {
                try (PreparedStatement statement = connection.prepareStatement("SELECT COUNT(*) AS count FROM dataset_ownership");
                     ResultSet resultSet = statement.executeQuery()) {
                    return resultSet.next() ? resultSet.getInt("count") : 0;
                }
            }
            try (PreparedStatement statement = connection.prepareStatement(
                "SELECT COUNT(*) AS count FROM dataset_ownership WHERE owner_user_id = ? OR is_public = 1"
            )) {
                statement.setInt(1, user.id());
                try (ResultSet resultSet = statement.executeQuery()) {
                    return resultSet.next() ? resultSet.getInt("count") : 0;
                }
            }
        } catch (SQLException exception) {
            throw new IllegalStateException("Failed to count accessible datasets", exception);
        }
    }

    public int countModelsForUser(DomainTypes.AppUser user) {
        String role = user == null ? "" : user.role();
        try (Connection connection = connect()) {
            if ("admin".equals(role)) {
                try (PreparedStatement statement = connection.prepareStatement("SELECT COUNT(*) AS count FROM model_ownership");
                     ResultSet resultSet = statement.executeQuery()) {
                    return resultSet.next() ? resultSet.getInt("count") : 0;
                }
            }
            try (PreparedStatement statement = connection.prepareStatement(
                "SELECT COUNT(*) AS count FROM model_ownership WHERE owner_user_id = ? OR is_public = 1"
            )) {
                statement.setInt(1, user.id());
                try (ResultSet resultSet = statement.executeQuery()) {
                    return resultSet.next() ? resultSet.getInt("count") : 0;
                }
            }
        } catch (SQLException exception) {
            throw new IllegalStateException("Failed to count accessible models", exception);
        }
    }
    private void initializeSchema() throws SQLException {
        try (Connection connection = connect(); Statement statement = connection.createStatement()) {
            statement.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('admin', 'user')),
                    is_disabled INTEGER NOT NULL DEFAULT 0,
                    is_flagged INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            );
            statement.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            );
            statement.execute(
                """
                CREATE TABLE IF NOT EXISTS dataset_ownership (
                    dataset_name TEXT PRIMARY KEY,
                    owner_user_id INTEGER NOT NULL,
                    is_public INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(owner_user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            );
            statement.execute(
                """
                CREATE TABLE IF NOT EXISTS model_ownership (
                    model_name TEXT PRIMARY KEY,
                    owner_user_id INTEGER NOT NULL,
                    is_public INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(owner_user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            );
            statement.execute(
                """
                CREATE TABLE IF NOT EXISTS class_advice_cache (
                    dataset_name TEXT NOT NULL,
                    class_name TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    advice_json TEXT NOT NULL,
                    source TEXT NOT NULL,
                    detail TEXT,
                    generated_by_user_id INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (dataset_name, class_name),
                    FOREIGN KEY(generated_by_user_id) REFERENCES users(id) ON DELETE SET NULL
                )
                """
            );
            statement.execute(
                "CREATE INDEX IF NOT EXISTS idx_class_advice_cache_class_name ON class_advice_cache(class_name)"
            );
            ensureColumn(connection, "users", "is_disabled", "INTEGER NOT NULL DEFAULT 0");
            ensureColumn(connection, "users", "is_flagged", "INTEGER NOT NULL DEFAULT 0");
            ensureColumn(connection, "dataset_ownership", "is_public", "INTEGER NOT NULL DEFAULT 0");
            ensureColumn(connection, "model_ownership", "is_public", "INTEGER NOT NULL DEFAULT 0");
            ensureColumn(connection, "class_advice_cache", "detail", "TEXT");
            ensureColumn(connection, "class_advice_cache", "generated_by_user_id", "INTEGER");
            ensureColumn(connection, "class_advice_cache", "created_at", "TEXT NOT NULL DEFAULT ''");
            ensureColumn(connection, "class_advice_cache", "updated_at", "TEXT NOT NULL DEFAULT ''");
        }
    }

    private void ensureColumn(Connection connection, String tableName, String columnName, String definition) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement("PRAGMA table_info(" + tableName + ")");
             ResultSet resultSet = statement.executeQuery()) {
            while (resultSet.next()) {
                if (columnName.equalsIgnoreCase(resultSet.getString("name"))) {
                    return;
                }
            }
        }
        try (Statement statement = connection.createStatement()) {
            statement.execute("ALTER TABLE " + tableName + " ADD COLUMN " + columnName + " " + definition);
        }
    }

    private void seedDefaultUsers() {
        if (getPrimaryAdminUser() != null) {
            return;
        }

        String adminUsername = env("BOOTSTRAP_ADMIN_USERNAME", "root");
        String adminPassword = env("BOOTSTRAP_ADMIN_PASSWORD", "");
        String userUsername = env("BOOTSTRAP_USER_USERNAME", "root_user");
        String userPassword = env("BOOTSTRAP_USER_PASSWORD", "");
        boolean allowInsecureDefaults = parseBoolean(env("ALLOW_INSECURE_DEFAULT_USERS", ""));

        if (allowInsecureDefaults) {
            if (adminPassword.isBlank()) {
                adminPassword = "root";
            }
            if (userPassword.isBlank()) {
                userPassword = "root";
            }
        }

        if (adminPassword.isBlank()) {
            throw new IllegalStateException("首次启动未检测到管理员账号，请先设置 BOOTSTRAP_ADMIN_PASSWORD 环境变量");
        }

        createUser(adminUsername, adminPassword, "admin", adminUsername, true);
        if (!userPassword.isBlank()) {
            createUser(userUsername, userPassword, "user", userUsername, true);
        }
    }

    private Connection connect() throws SQLException {
        Connection connection = DriverManager.getConnection("jdbc:sqlite:" + properties.resolveAuthDbPath());
        try (Statement statement = connection.createStatement()) {
            statement.execute("PRAGMA foreign_keys = ON");
        }
        return connection;
    }

    private DomainTypes.AppUser rowToUser(ResultSet resultSet) throws SQLException {
        return new DomainTypes.AppUser(
            resultSet.getInt("id"),
            resultSet.getString("username"),
            resultSet.getString("display_name"),
            resultSet.getString("role"),
            resultSet.getBoolean("is_disabled"),
            resultSet.getBoolean("is_flagged"),
            resultSet.getString("created_at"),
            hasColumn(resultSet, "dataset_count") ? resultSet.getInt("dataset_count") : 0,
            hasColumn(resultSet, "model_count") ? resultSet.getInt("model_count") : 0
        );
    }

    private DomainTypes.DatasetOwnership rowToDatasetOwnership(ResultSet resultSet) throws SQLException {
        return new DomainTypes.DatasetOwnership(
            resultSet.getString("dataset_name"),
            resultSet.getInt("owner_user_id"),
            resultSet.getBoolean("is_public"),
            resultSet.getString("created_at"),
            readNullableString(resultSet, "owner_username"),
            readNullableString(resultSet, "owner_display_name"),
            readNullableString(resultSet, "owner_role")
        );
    }

    private DomainTypes.ModelOwnership rowToModelOwnership(ResultSet resultSet) throws SQLException {
        return new DomainTypes.ModelOwnership(
            resultSet.getString("model_name"),
            resultSet.getInt("owner_user_id"),
            resultSet.getBoolean("is_public"),
            resultSet.getString("created_at"),
            readNullableString(resultSet, "owner_username"),
            readNullableString(resultSet, "owner_display_name"),
            readNullableString(resultSet, "owner_role")
        );
    }
    private String normalizeUsername(String username) {
        String raw = USERNAME_SANITIZER.matcher(username == null ? "" : username.trim()).replaceAll("_");
        String normalized = UNDERSCORE_COLLAPSE.matcher(raw).replaceAll("_");
        normalized = trimDotsAndUnderscores(normalized);
        if (normalized.length() < 3) {
            throw new PlantApiException(HttpStatus.BAD_REQUEST, "用户名至少需要 3 个字符，只能包含字母、数字、下划线或中划线");
        }
        return normalized.length() > 48 ? normalized.substring(0, 48) : normalized;
    }

    private String normalizeDisplayName(String displayName, String fallbackUsername) {
        String normalized = (displayName == null ? "" : displayName).trim().replaceAll("\\s+", " ");
        if (normalized.isBlank()) {
            return fallbackUsername;
        }
        return normalized.length() > 48 ? normalized.substring(0, 48) : normalized;
    }

    private String trimDotsAndUnderscores(String value) {
        int start = 0;
        int end = value.length();
        while (start < end && (value.charAt(start) == '.' || value.charAt(start) == '_')) {
            start += 1;
        }
        while (end > start && (value.charAt(end - 1) == '.' || value.charAt(end - 1) == '_')) {
            end -= 1;
        }
        return value.substring(start, end);
    }

    private String hashPassword(String password, String saltHex) {
        try {
            byte[] salt = saltHex == null || saltHex.isBlank() ? secureRandom.generateSeed(16) : hexToBytes(saltHex);
            KeySpec keySpec = new PBEKeySpec((password == null ? "" : password).toCharArray(), salt, PASSWORD_ITERATIONS, 256);
            SecretKeyFactory factory = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256");
            byte[] digest = factory.generateSecret(keySpec).getEncoded();
            return PASSWORD_ITERATIONS + "$" + bytesToHex(salt) + "$" + bytesToHex(digest);
        } catch (Exception exception) {
            throw new IllegalStateException("Failed to hash password", exception);
        }
    }

    private boolean verifyPassword(String password, String passwordHash) {
        try {
            String[] parts = (passwordHash == null ? "" : passwordHash).split("\\$", 3);
            if (parts.length != 3) {
                return false;
            }
            int iterations = Integer.parseInt(parts[0]);
            byte[] salt = hexToBytes(parts[1]);
            byte[] expected = hexToBytes(parts[2]);
            KeySpec keySpec = new PBEKeySpec((password == null ? "" : password).toCharArray(), salt, iterations, expected.length * 8);
            SecretKeyFactory factory = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256");
            byte[] candidate = factory.generateSecret(keySpec).getEncoded();
            return MessageDigest.isEqual(candidate, expected);
        } catch (Exception exception) {
            return false;
        }
    }

    private String hashSessionToken(String token) {
        String safeToken = token == null ? "" : token.trim();
        if (safeToken.isEmpty()) {
            return "";
        }
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] hashed = digest.digest(safeToken.getBytes(StandardCharsets.UTF_8));
            return SESSION_TOKEN_PREFIX + "$" + bytesToHex(hashed);
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("Failed to hash session token", exception);
        }
    }

    private String generateSessionToken() {
        byte[] bytes = new byte[32];
        secureRandom.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    private void migratePlainSessionToken(String plainToken, String tokenHash) throws SQLException {
        try (Connection connection = connect();
             PreparedStatement statement = connection.prepareStatement(
                 "UPDATE sessions SET token = ? WHERE token = ?"
             )) {
            statement.setString(1, tokenHash);
            statement.setString(2, plainToken);
            statement.executeUpdate();
        }
    }

    private void deleteExactSessionToken(String sessionToken) throws SQLException {
        try (Connection connection = connect();
             PreparedStatement statement = connection.prepareStatement("DELETE FROM sessions WHERE token = ?")) {
            statement.setString(1, sessionToken);
            statement.executeUpdate();
        }
    }

    private boolean hasColumn(ResultSet resultSet, String columnName) throws SQLException {
        ResultSetMetaData metadata = resultSet.getMetaData();
        for (int index = 1; index <= metadata.getColumnCount(); index += 1) {
            if (columnName.equalsIgnoreCase(metadata.getColumnLabel(index))) {
                return true;
            }
        }
        return false;
    }

    private String readNullableString(ResultSet resultSet, String columnName) throws SQLException {
        if (!hasColumn(resultSet, columnName)) {
            return null;
        }
        String value = resultSet.getString(columnName);
        return value == null || value.isBlank() ? null : value;
    }

    private String bytesToHex(byte[] bytes) {
        StringBuilder builder = new StringBuilder(bytes.length * 2);
        for (byte current : bytes) {
            builder.append(String.format(Locale.ROOT, "%02x", current));
        }
        return builder.toString();
    }

    private byte[] hexToBytes(String hex) {
        if (hex == null || (hex.length() % 2) != 0) {
            throw new IllegalArgumentException("Invalid hex string");
        }
        byte[] bytes = new byte[hex.length() / 2];
        for (int index = 0; index < hex.length(); index += 2) {
            bytes[index / 2] = (byte) Integer.parseInt(hex.substring(index, index + 2), 16);
        }
        return bytes;
    }

    private OffsetDateTime utcNow() {
        return OffsetDateTime.now(ZoneOffset.UTC).truncatedTo(ChronoUnit.SECONDS);
    }

    private String utcTimestamp() {
        return utcNow().toString();
    }

    private String env(String name, String defaultValue) {
        String value = System.getenv(name);
        return value == null ? defaultValue : value.trim();
    }

    private boolean parseBoolean(String value) {
        String normalized = value == null ? "" : value.trim().toLowerCase(Locale.ROOT);
        return normalized.equals("1") || normalized.equals("true") || normalized.equals("yes") || normalized.equals("on");
    }
}