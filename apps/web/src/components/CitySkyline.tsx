// Decorative NYC skyline silhouette for the auth brand panel -- hand-built inline SVG (no
// external image asset/network fetch) so the login page stays self-contained and crisp at any
// size. A dusk sky gradient (defined here, not the parent's background) guarantees the
// near-black building silhouettes actually contrast against it -- three depth layers (back to
// front, hazier to crisp) plus lit windows on the front layer only, tying into the tier
// system's amber accent without competing with it.
export function CitySkyline() {
  return (
    <svg
      viewBox="0 0 800 320"
      preserveAspectRatio="xMidYMax slice"
      className="absolute inset-0 h-full w-full"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="dusk-sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#020617" />
          <stop offset="55%" stopColor="#0f172a" />
          <stop offset="100%" stopColor="#3b2a1a" />
        </linearGradient>
      </defs>

      <rect x="0" y="0" width="800" height="320" fill="url(#dusk-sky)" />

      {/* Back layer -- hazy, near the sky's own tone */}
      <g fill="#0f172a" opacity="0.6">
        <rect x="-10" y="150" width="70" height="170" />
        <rect x="55" y="110" width="55" height="210" />
        <rect x="120" y="170" width="90" height="150" />
        <rect x="205" y="90" width="45" height="230" />
        <rect x="255" y="140" width="80" height="180" />
        <rect x="345" y="120" width="60" height="200" />
        <rect x="415" y="160" width="100" height="160" />
        <rect x="520" y="95" width="50" height="225" />
        <rect x="575" y="150" width="85" height="170" />
        <rect x="665" y="115" width="65" height="205" />
        <rect x="735" y="165" width="75" height="155" />
      </g>

      {/* Mid layer */}
      <g fill="#020617" opacity="0.75">
        <rect x="10" y="190" width="60" height="130" />
        <rect x="90" y="150" width="45" height="170" />
        <rect x="150" y="200" width="70" height="120" />
        <rect x="235" y="130" width="50" height="190" />
        <rect x="300" y="175" width="65" height="145" />
        <rect x="380" y="150" width="55" height="170" />
        <rect x="450" y="190" width="80" height="130" />
        <rect x="545" y="140" width="45" height="180" />
        <rect x="605" y="185" width="60" height="135" />
        <rect x="680" y="155" width="50" height="165" />
        <rect x="745" y="195" width="55" height="125" />
      </g>

      {/* Front layer -- fully opaque, crisp silhouette */}
      <g fill="#020617">
        <rect x="0" y="235" width="50" height="85" />
        <rect x="60" y="200" width="40" height="120" />
        <rect x="110" y="250" width="55" height="70" />
        <rect x="175" y="180" width="35" height="140" />
        <rect x="220" y="225" width="60" height="95" />
        <rect x="290" y="210" width="45" height="110" />
        <rect x="345" y="240" width="70" height="80" />
        <rect x="425" y="195" width="40" height="125" />
        <rect x="475" y="230" width="55" height="90" />
        <rect x="540" y="205" width="45" height="115" />
        <rect x="595" y="245" width="65" height="75" />
        <rect x="670" y="215" width="40" height="105" />
        <rect x="720" y="240" width="50" height="80" />
        <rect x="780" y="220" width="30" height="100" />
      </g>

      {/* Lit windows -- sparse and deliberate, only on the front (fully opaque) buildings so
          they read clearly against a solid dark fill */}
      <g fill="#fbbf24">
        <rect x="15" y="255" width="6" height="8" />
        <rect x="30" y="270" width="6" height="8" />
        <rect x="15" y="285" width="6" height="8" />
        <rect x="72" y="220" width="6" height="8" />
        <rect x="72" y="245" width="6" height="8" />
        <rect x="72" y="270" width="6" height="8" />
        <rect x="185" y="205" width="6" height="8" />
        <rect x="185" y="235" width="6" height="8" />
        <rect x="185" y="265" width="6" height="8" />
        <rect x="235" y="250" width="6" height="8" />
        <rect x="235" y="280" width="6" height="8" />
        <rect x="360" y="260" width="6" height="8" />
        <rect x="360" y="285" width="6" height="8" />
        <rect x="435" y="220" width="6" height="8" />
        <rect x="435" y="245" width="6" height="8" />
        <rect x="435" y="270" width="6" height="8" />
        <rect x="555" y="235" width="6" height="8" />
        <rect x="555" y="260" width="6" height="8" />
        <rect x="610" y="265" width="6" height="8" />
        <rect x="610" y="290" width="6" height="8" />
        <rect x="680" y="240" width="6" height="8" />
        <rect x="680" y="265" width="6" height="8" />
        <rect x="730" y="260" width="6" height="8" />
        <rect x="730" y="285" width="6" height="8" />
        <rect x="790" y="245" width="6" height="8" />
      </g>
    </svg>
  );
}
