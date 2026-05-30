export const navItems = [
  { path: "/overview", label: "Overview", icon: "map" },
  { path: "/editor", label: "Editor", icon: "edit_road" },
  { path: "/registered-intersections", label: "Registered Regions", icon: "location_on" },
  { path: "/settings", label: "Settings", icon: "settings" },
];

export const dashboardMetrics = [
  { label: "Avg. Speed", value: "42.8", suffix: "km/h", trend: "+12%", tone: "positive" },
  { label: "Congestion Index", value: "1.24", suffix: "Level", trend: "Stable", tone: "alert" },
  { label: "Active Sensors", value: "12,402", suffix: "Online", trend: "99.8% UP", tone: "positive" },
  { label: "Carbon Reduction", value: "2.4", suffix: "Tons / hr", trend: "Eco", tone: "accent" },
];

export const incidents = [
  {
    title: "Stalled Vehicle - North Hwy",
    time: "Reported 4 mins ago",
    tags: ["Lane 2 Blocked", "High Priority"],
    icon: "emergency_home",
    tone: "critical",
  },
  {
    title: "Maintenance - Sector 7",
    time: "Scheduled until 18:00",
    tags: ["No Delay"],
    icon: "construction",
    tone: "positive",
  },
  {
    title: "Fender Bender - City Center",
    time: "Resolving - 12 mins ago",
    tags: ["Resolved"],
    icon: "minor_crash",
    tone: "neutral",
  },
];

export const hourlyTraffic = [20, 15, 10, 12, 25, 45, 75, 90, 85, 70, 60, 40, 30, 25];

export const analyticsBars = [
  { day: "Mon", current: 80, previous: 60 },
  { day: "Tue", current: 90, previous: 70 },
  { day: "Wed", current: 100, previous: 85 },
  { day: "Thu", current: 65, previous: 55 },
  { day: "Fri", current: 60, previous: 50 },
  { day: "Sat", current: 95, previous: 90 },
  { day: "Sun", current: 50, previous: 40 },
];

export const optimizationStats = [
  { label: "Throughput Efficiency", delta: "+38%", after: 82, before: 44, tone: "positive" },
  { label: "Idling Time", delta: "-52%", after: 28, before: 80, tone: "critical" },
  { label: "Fuel Consumption", delta: "-19%", after: 65, before: 84, tone: "accent" },
];

export const analyticsTable = [
  { id: "GR-7729", location: "Central Avenue & 5th St.", status: "Optimized", flow: "0.92" },
  { id: "GR-1044", location: "Skyline Bridge (Eastbound)", status: "Optimized", flow: "0.88" },
  { id: "GR-9021", location: "Old Town Square Cluster", status: "Manual Override", flow: "0.45" },
];

export const logStats = [
  { label: "Total Events (24h)", value: "12,842", meta: "+12%" },
  { label: "Critical Alerts", value: "03", meta: "-2", tone: "critical" },
  { label: "Active Sensors", value: "99.8%", meta: "Stable" },
  { label: "Avg Response", value: "1.2s", meta: "ms" },
];

export const logRows = [
  {
    timestamp: "2026-04-22 14:22:01",
    intersection: "INT-7742 (Broadway & 5th)",
    event: "Sensor Offline",
    severity: "CRITICAL",
    status: "Dispatching...",
  },
  {
    timestamp: "2026-04-22 14:19:45",
    intersection: "INT-1209 (Oak & Pine)",
    event: "High Volume Alert",
    severity: "WARNING",
    status: "Optimizing Flow",
  },
  {
    timestamp: "2026-04-22 14:15:12",
    intersection: "INT-8821 (Market St.)",
    event: "Signal Cycle Change",
    severity: "INFO",
    status: "Completed",
  },
  {
    timestamp: "2026-04-22 14:02:33",
    intersection: "INT-4410 (Main & West)",
    event: "System Diagnostics",
    severity: "INFO",
    status: "Success",
  },
  {
    timestamp: "2026-04-22 13:55:00",
    intersection: "INT-9002 (Expressway E4)",
    event: "Gridlock Pattern",
    severity: "CRITICAL",
    status: "Priority Override",
  },
];

export const intersections = [
  { name: "Broadway & 42nd St", district: "Mid-Town Hub", status: "SYNCED", tags: ["HIGH FLOW", "4-WAY"] },
  { name: "5th Ave & East 23rd", district: "Flatiron District", status: "IDLE", tags: ["MED FLOW"] },
  { name: "Madison & 57th St", district: "Plaza District", status: "ALERT", tags: ["CONGESTION"] },
  { name: "Park Ave & 47th St", district: "Grand Central", status: "IDLE", tags: [] },
];

export const settingsChannels = [
  { label: "Critical Traffic Alerts", enabled: true, icon: "warning" },
  { label: "System Maintenance", enabled: true, icon: "construction" },
  { label: "Node Connectivity Issues", enabled: false, icon: "router" },
];
