/** Team colours for the 2024-2026 grids, keyed by the team names the API returns. */
export const TEAM_COLORS: Record<string, string> = {
  "Red Bull Racing": "#3671c6",
  McLaren: "#ff8000",
  Ferrari: "#e8002d",
  Mercedes: "#27f4d2",
  "Aston Martin": "#229971",
  Alpine: "#0093cc",
  Williams: "#64c4ff",
  "Racing Bulls": "#6692ff",
  "Kick Sauber": "#52e252",
  Audi: "#f50537",
  "Haas F1 Team": "#b6babd",
  Cadillac: "#d4d4d8",
};

export const UNKNOWN_TEAM_COLOR = "#6b7280";

/** Other spellings seen across seasons and data sources, mapped to a `TEAM_COLORS` key. */
const ALIASES: Record<string, string> = {
  "red bull": "Red Bull Racing",
  "oracle red bull racing": "Red Bull Racing",
  "mclaren f1 team": "McLaren",
  "scuderia ferrari": "Ferrari",
  "mercedes-amg petronas": "Mercedes",
  "aston martin aramco": "Aston Martin",
  "alpine f1 team": "Alpine",
  "bwt alpine f1 team": "Alpine",
  "williams racing": "Williams",
  rb: "Racing Bulls",
  "visa cash app rb": "Racing Bulls",
  "rb f1 team": "Racing Bulls",
  "visa cash app racing bulls": "Racing Bulls",
  sauber: "Kick Sauber",
  "stake f1 team kick sauber": "Kick Sauber",
  "audi f1 team": "Audi",
  haas: "Haas F1 Team",
  "moneygram haas f1 team": "Haas F1 Team",
  "cadillac f1 team": "Cadillac",
};

const BY_LOWER = new Map(Object.entries(TEAM_COLORS).map(([name, color]) => [name.toLowerCase(), color]));

/** Colour for a team name; grey when the team is unknown. */
export function teamColor(team: string | null | undefined): string {
  if (!team) return UNKNOWN_TEAM_COLOR;
  const key = team.trim().toLowerCase();
  const direct = BY_LOWER.get(key);
  if (direct) return direct;
  const alias = ALIASES[key];
  return alias ? TEAM_COLORS[alias] : UNKNOWN_TEAM_COLOR;
}
