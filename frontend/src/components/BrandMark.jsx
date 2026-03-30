export function BrandMark({ compact = false }) {
  return (
    <div className={`brand-mark${compact ? " brand-mark--compact" : ""}`}>
      <span className="brand-mark__glyph" aria-hidden="true">
        <svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
          <circle cx="24" cy="24" r="14.5" stroke="rgba(244,255,247,0.28)" strokeWidth="1.2" />
          <path d="M24 12V36" stroke="rgba(244,255,247,0.16)" strokeWidth="1" strokeLinecap="round" />
          <path d="M12 24H36" stroke="rgba(244,255,247,0.16)" strokeWidth="1" strokeLinecap="round" />
          <path
            d="M23.8 30.6C17.4 27.7 14.8 21.3 17.1 14.7C22.8 15.8 26 20.1 26.2 26.3C26.2 28.1 25.4 29.5 23.8 30.6Z"
            fill="#A6D66A"
          />
          <path
            d="M24.2 30.6C30.6 27.7 33.2 21.3 30.9 14.7C25.2 15.8 22 20.1 21.8 26.3C21.8 28.1 22.6 29.5 24.2 30.6Z"
            fill="#6FB774"
          />
          <path d="M24 22.6V35.8" stroke="#F4FFF7" strokeWidth="1.7" strokeLinecap="round" />
          <path d="M24 35.7C21.7 33.7 19.5 32.4 17.4 31.8" stroke="#F4FFF7" strokeWidth="1.3" strokeLinecap="round" />
          <path d="M24 35.7C26.3 33.7 28.5 32.4 30.6 31.8" stroke="#F4FFF7" strokeWidth="1.3" strokeLinecap="round" />
          <circle cx="24" cy="12.2" r="2.6" fill="#D6A062" />
          <circle cx="24" cy="24" r="3.5" fill="#143626" stroke="#EAF7E4" strokeWidth="1.3" />
        </svg>
      </span>
      <div className="brand-mark__copy">
        <strong>PlantOps</strong>
        <span>植物病害识别平台</span>
      </div>
    </div>
  );
}
