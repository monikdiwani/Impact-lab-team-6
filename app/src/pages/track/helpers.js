/* Small helpers local to the complaint tracker page. */

export const LANG = { en: "English", hi: "Hindi", mr: "Marathi", "hi-en": "Hinglish" };

/** BCP 47 tag for the lang attribute, so screen readers and fonts pick the right script */
export const LANG_ATTR = { en: "en", hi: "hi", mr: "mr", "hi-en": "hi-Latn" };

export const WARD_SOURCE = {
  given: "given in the complaint",
  gps: "from GPS",
  locality: "from locality name",
};

/*
  Plain-language meaning of every complaint status in the data.
  tone drives the badge colour: only real state gets semantic colour.
*/
export const STATUS = {
  Resolved: {
    tone: "badge-success",
    short: "Repaired",
    title: "Repaired",
    text: "A repair crew was sent and the job was marked complete.",
  },
  "Closed - Duplicate": {
    tone: "badge-ghost",
    short: "Duplicate",
    title: "Joined to an earlier report",
    text: "Someone had already reported the same problem, so this report was closed and follows that repair job.",
  },
  Open: {
    tone: "badge-warning badge-solid",
    short: "Open",
    title: "Waiting for a repair crew",
    text: "The complaint is logged but no repair job has been assigned yet.",
  },
  "In Progress": {
    tone: "badge-warning badge-solid",
    short: "In progress",
    title: "Being looked at, no repair job yet",
    text: "The ward office has picked this up, but no repair job has been assigned yet.",
  },
  "Forwarded to MMRDA/PWD": {
    tone: "badge-ghost",
    short: "Forwarded",
    title: "Passed to another road agency",
    text: "This road is looked after by MMRDA (the regional development authority) or PWD (the state public works department), not the BMC. The complaint was sent to them, so no BMC money was spent here.",
  },
  "Forwarded to SWM dept": {
    tone: "badge-ghost",
    short: "Forwarded",
    title: "Passed to the solid waste department",
    text: "The cause looked like garbage or debris rather than road damage, so it went to the solid waste management (SWM) team instead of a road contractor.",
  },
  "Rejected - Not road issue": {
    tone: "badge-ghost",
    short: "Closed",
    title: "Closed: not a road problem",
    text: "The ward office decided this was not a road problem, so no road repair was ordered.",
  },
  "Rejected - Not BMC road": {
    tone: "badge-ghost",
    short: "Closed",
    title: "Closed: not a BMC road",
    text: "The road does not belong to the BMC, so the BMC did not order a repair. The owner agency is responsible for it.",
  },
};

export const statusInfo = (s) => STATUS[s] || { tone: "badge-ghost", short: s, title: s, text: "" };

export const isOpen = (s) => s === "Open" || s === "In Progress";

/** complaint IDs: "BMC25-000005", "bmc25-5", "bmc 25 000005" all resolve; returns null if not an ID */
export function parseComplaintId(v) {
  const m = /^\s*bmc\s*25\s*-?\s*(\d{1,6})\s*$/i.exec(v || "");
  return m ? `BMC25-${m[1].padStart(6, "0")}` : null;
}

export function excerpt(s, n = 100) {
  const t = (s || "").trim();
  return t.length > n ? `${t.slice(0, n).trimEnd()}...` : t;
}

/** hours between two "YYYY-MM-DD HH:MM" stamps */
export function hoursBetween(a, b) {
  if (!a || !b) return null;
  const p = (s) => new Date(s.replace(" ", "T") + ":00").getTime();
  return (p(b) - p(a)) / 36e5;
}

/** "135 h (5.6 days)" for long spans, "19 h" for short ones */
export function span(h, numFn) {
  if (h == null) return "-";
  const hrs = `${numFn(h)} h`;
  return h >= 48 ? `${hrs} (${numFn(h / 24, 1)} days)` : hrs;
}

export const same = (a, b) => (a || "").trim() === (b || "").trim();
