// Original illustrations for MediAssist (simple flat SVGs, no third-party artwork).

export function Logo({ className = "brand-logo" }) {
  return (
    <svg className={className} viewBox="0 0 48 48" aria-hidden="true">
      <path d="M24 3 6 10v13c0 11 7.7 19.6 18 22 10.3-2.4 18-11 18-22V10L24 3Z" fill="#5156be" />
      <path d="M24 8.5 11 13.6v9.6c0 8.2 5.6 14.6 13 16.6 7.4-2 13-8.4 13-16.6v-9.6L24 8.5Z" fill="#e9e8fd" />
      <path d="M20.5 15h7v6.5H34v7h-6.5V35h-7v-6.5H14v-7h6.5z" fill="#ee3158" />
    </svg>
  );
}

// Calendar with a heart-pulse and a chat bubble – used in the welcome banner
export function BannerArt() {
  return (
    <svg viewBox="0 0 160 120" aria-hidden="true">
      <ellipse cx="80" cy="108" rx="62" ry="8" fill="#f1f0fe" />
      <rect x="22" y="22" width="92" height="80" rx="12" fill="#fff" stroke="#e9e8fd" strokeWidth="3" />
      <rect x="22" y="22" width="92" height="22" rx="12" fill="#5156be" />
      <rect x="22" y="34" width="92" height="10" fill="#5156be" />
      <rect x="40" y="14" width="6" height="16" rx="3" fill="#172b4c" />
      <rect x="90" y="14" width="6" height="16" rx="3" fill="#172b4c" />
      {[0, 1, 2, 3].map((c) => [0, 1].map((r) => (
        <rect key={`${c}${r}`} x={34 + c * 18} y={54 + r * 18} width="12" height="10" rx="3"
              fill={c === 2 && r === 0 ? "#ffa800" : "#e9e8fd"} />
      )))}
      <path d="M34 92h14l5-9 7 16 6-12 4 5h14" fill="none" stroke="#ee3158" strokeWidth="3"
            strokeLinecap="round" strokeLinejoin="round" />
      <g transform="translate(112 46)">
        <path d="M6 0h30a6 6 0 0 1 6 6v18a6 6 0 0 1-6 6H18l-9 8v-8H6a6 6 0 0 1-6-6V6a6 6 0 0 1 6-6Z" fill="#3596f7" />
        <circle cx="13" cy="15" r="3" fill="#fff" /><circle cx="21" cy="15" r="3" fill="#fff" /><circle cx="29" cy="15" r="3" fill="#fff" />
      </g>
    </svg>
  );
}

// Phone with a chat – sidebar card ("Telegram bot")
export function PhoneArt() {
  return (
    <svg viewBox="0 0 140 110" aria-hidden="true">
      <circle cx="70" cy="58" r="46" fill="#fff" opacity=".7" />
      <rect x="46" y="10" width="48" height="92" rx="10" fill="#172b4c" />
      <rect x="50" y="18" width="40" height="72" rx="5" fill="#fff" />
      <rect x="55" y="25" width="24" height="9" rx="4.5" fill="#e9e8fd" />
      <rect x="62" y="38" width="23" height="9" rx="4.5" fill="#5156be" />
      <rect x="55" y="51" width="27" height="9" rx="4.5" fill="#e9e8fd" />
      <rect x="64" y="64" width="21" height="9" rx="4.5" fill="#5156be" />
      <circle cx="70" cy="96" r="2.5" fill="#fff" />
      <g transform="translate(88 20)">
        <circle cx="16" cy="16" r="16" fill="#ffa800" />
        <path d="M9 16h14M16 9v14" stroke="#fff" strokeWidth="4" strokeLinecap="round" />
      </g>
      <g transform="translate(18 56)">
        <circle cx="13" cy="13" r="13" fill="#05825f" />
        <path d="m7 13 4 4 8-8" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
      </g>
    </svg>
  );
}

// Login page artwork: shield + stethoscope + calendar tiles
export function LoginArt() {
  return (
    <svg viewBox="0 0 320 260" aria-hidden="true">
      <ellipse cx="160" cy="236" rx="120" ry="12" fill="#ecebfd" />
      <rect x="40" y="70" width="110" height="130" rx="16" fill="#fff" stroke="#e9e8fd" strokeWidth="4" />
      <rect x="40" y="70" width="110" height="30" rx="16" fill="#5156be" />
      <rect x="40" y="86" width="110" height="14" fill="#5156be" />
      {[0, 1, 2].map((c) => [0, 1, 2].map((r) => (
        <rect key={`${c}${r}`} x={56 + c * 28} y={114 + r * 26} width="20" height="16" rx="4"
              fill={c === 1 && r === 1 ? "#ffa800" : "#e9e8fd"} />
      )))}
      <g transform="translate(150 30)">
        <path d="M70 0 10 22v42c0 37 25.6 66 60 74 34.4-8 60-37 60-74V22L70 0Z" fill="#5156be" />
        <path d="M70 16 26 32v32c0 27 18.6 48.4 44 55 25.4-6.6 44-28 44-55V32L70 16Z" fill="#e9e8fd" />
        <path d="M58 40h24v20h20v24H82v20H58V84H38V60h20z" fill="#ee3158" />
      </g>
      <path d="M232 180c0 22-18 30-30 30s-26-10-26-28" fill="none" stroke="#172b4c" strokeWidth="6" strokeLinecap="round" />
      <circle cx="176" cy="178" r="10" fill="#3596f7" stroke="#172b4c" strokeWidth="5" />
    </svg>
  );
}
