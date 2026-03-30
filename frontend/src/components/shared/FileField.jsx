import { useRef } from "react";

export function FileField({
  label,
  accept,
  file,
  onChange,
  buttonLabel = "选择文件",
  disabled = false,
  required = false,
}) {
  const inputRef = useRef(null);

  return (
    <label className="native-field native-file-field">
      <span>{label}</span>
      <input
        ref={inputRef}
        className="native-file-input"
        type="file"
        accept={accept}
        required={required}
        disabled={disabled}
        onChange={(event) => onChange?.(event.target.files?.[0] || null)}
      />
      <div className="native-file-field__surface">
        <button
          type="button"
          className="secondary native-file-field__button"
          onClick={() => inputRef.current?.click()}
          disabled={disabled}
        >
          {buttonLabel}
        </button>
        <span className="native-file-field__meta">{file?.name || "未选择文件"}</span>
      </div>
    </label>
  );
}
