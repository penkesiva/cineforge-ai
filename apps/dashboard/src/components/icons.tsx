import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function Svg({ size = 18, children, ...rest }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {children}
    </svg>
  );
}

export const IconOverview = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3" y="3" width="7" height="9" rx="1.5" />
    <rect x="14" y="3" width="7" height="5" rx="1.5" />
    <rect x="14" y="12" width="7" height="9" rx="1.5" />
    <rect x="3" y="16" width="7" height="5" rx="1.5" />
  </Svg>
);

export const IconFilm = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3" y="3" width="18" height="18" rx="2" />
    <path d="M7 3v18M17 3v18M3 7.5h4M3 12h18M3 16.5h4M17 7.5h4M17 16.5h4" />
  </Svg>
);

export const IconAgents = (p: IconProps) => (
  <Svg {...p}>
    <rect x="6" y="6" width="12" height="12" rx="2" />
    <rect x="9.5" y="9.5" width="5" height="5" rx="1" />
    <path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4" />
  </Svg>
);

export const IconCoins = (p: IconProps) => (
  <Svg {...p}>
    <ellipse cx="9" cy="7" rx="6" ry="3" />
    <path d="M3 7v5c0 1.66 2.69 3 6 3s6-1.34 6-3V7" />
    <path d="M9 18c0 1.66 2.69 3 6 3s6-1.34 6-3v-5c0-1.5-2.2-2.75-5.1-2.97" />
  </Svg>
);

export const IconCheck = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 12.5l4.5 4.5L19 7.5" />
  </Svg>
);

export const IconAlert = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3.5l9.5 16.5h-19z" />
    <path d="M12 10v4.5M12 17.5v.01" />
  </Svg>
);

export const IconInfo = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 11v5.5M12 7.5v.01" />
  </Svg>
);

export const IconX = (p: IconProps) => (
  <Svg {...p}>
    <path d="M6 6l12 12M18 6L6 18" />
  </Svg>
);

export const IconStop = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M8.5 8.5l7 7M15.5 8.5l-7 7" />
  </Svg>
);

export const IconPlay = (p: IconProps) => (
  <Svg {...p}>
    <path d="M7 4.5v15l12-7.5z" />
  </Svg>
);

export const IconSend = (p: IconProps) => (
  <Svg {...p}>
    <path d="M21 3L10 14M21 3l-7 18-4-7-7-4z" />
  </Svg>
);

export const IconSpark = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z" />
    <path d="M19 15l.7 2.3L22 18l-2.3.7L19 21l-.7-2.3L16 18l2.3-.7z" />
  </Svg>
);

export const IconPlus = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 5v14M5 12h14" />
  </Svg>
);

export const IconRefresh = (p: IconProps) => (
  <Svg {...p}>
    <path d="M20 11a8 8 0 10-2.3 5.7M20 4v7h-7" />
  </Svg>
);

export const IconExternal = (p: IconProps) => (
  <Svg {...p}>
    <path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 01-1 1H5a1 1 0 01-1-1V7a1 1 0 011-1h5" />
  </Svg>
);

export const IconPlug = (p: IconProps) => (
  <Svg {...p}>
    <path d="M9 2v5M15 2v5" />
    <path d="M6 7h12v4a6 6 0 01-12 0z" />
    <path d="M12 17v5" />
  </Svg>
);

export const IconPalette = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3a9 9 0 100 18c1.1 0 1.8-.8 1.8-1.8 0-.5-.2-.9-.5-1.2-.3-.3-.5-.7-.5-1.2 0-1 .8-1.8 1.8-1.8H17a4 4 0 004-4c0-4.4-4-8-9-8z" />
    <circle cx="7.5" cy="11" r="1" />
    <circle cx="10" cy="7" r="1" />
    <circle cx="15" cy="7.5" r="1" />
  </Svg>
);

export const IconChevronUp = (p: IconProps) => (
  <Svg {...p}>
    <path d="M6 15l6-6 6 6" />
  </Svg>
);

export const IconChevronDown = (p: IconProps) => (
  <Svg {...p}>
    <path d="M6 9l6 6 6-6" />
  </Svg>
);

export const IconKey = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="8" cy="15" r="4" />
    <path d="M11 12l9-9M17 6l3 3M15 8l2 2" />
  </Svg>
);

export const IconSearch = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="11" cy="11" r="6" />
    <path d="M20 20l-3.5-3.5" />
  </Svg>
);

export const IconBug = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 7a4 4 0 014 4v5a4 4 0 01-8 0v-5a4 4 0 014-4z" />
    <path d="M9 9V6.5M15 9V6.5M8 12H4.5M19.5 12H16M8 16H5M19 16h-3M12 7V4" />
  </Svg>
);

export function Logo({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <defs>
        <linearGradient id="cf-logo" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#fcd88a" />
          <stop offset="1" stopColor="#c9801e" />
        </linearGradient>
      </defs>
      <rect x="1" y="1" width="30" height="30" rx="8" fill="#10101a" stroke="url(#cf-logo)" strokeWidth="1.5" />
      <path d="M12 9.5v13l10.5-6.5z" fill="url(#cf-logo)" />
      <path d="M6 8v16M26 8v16" stroke="#2f2f3f" strokeWidth="2" strokeDasharray="2 2.5" />
    </svg>
  );
}
