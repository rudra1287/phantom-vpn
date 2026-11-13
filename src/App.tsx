import { useEffect, useState } from "react";

const API_BASE = import.meta.env.DEV ? "" : "https://phantom-vpn-api.onrender.com";

type IconProps = {
  size?: number;
  className?: string;
};

const iconProps = (size: number, className?: string) => ({
  width: size,
  height: size,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  className,
});

const Shield = ({ size = 18 }: IconProps) => (
  <svg {...iconProps(size)}>
    <path d="M12 3l7 3v6c0 5-3.5 9-7 10-3.5-1-7-5-7-10V6l7-3z" />
    <path d="m9 12 2 2 4-4" />
  </svg>
);

const Globe = ({ size = 18 }: IconProps) => (
  <svg {...iconProps(size)}>
    <circle cx="12" cy="12" r="9" />
    <path d="M3 12h18M12 3a15 15 0 0 1 0 18M12 3a15 15 0 0 0 0 18" />
  </svg>
);

const Server = ({ size = 18 }: IconProps) => (
  <svg {...iconProps(size)}>
    <rect x="4" y="4" width="16" height="7" rx="2" />
    <rect x="4" y="13" width="16" height="7" rx="2" />
    <path d="M8 8h.01M8 17h.01" />
  </svg>
);

const Smartphone = ({ size = 18 }: IconProps) => (
  <svg {...iconProps(size)}>
    <rect x="7" y="2.5" width="10" height="19" rx="2" />
    <path d="M11 18h2" />
  </svg>
);

const Settings = ({ size = 18 }: IconProps) => (
  <svg {...iconProps(size)}>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15l1.4 1.4-2.8 2.8-1.4-1.4a7 7 0 0 1-2 .8V21h-4v-2.4a7 7 0 0 1-2-.8l-1.4 1.4-2.8-2.8L5.8 15a7 7 0 0 1-.8-2H2v-4h3a7 7 0 0 1 .8-2L4.4 5.6l2.8-2.8L8.6 4.2a7 7 0 0 1 2-.8V1h4v2.4a7 7 0 0 1 2 .8L18 2.8l2.8 2.8L19.4 7a7 7 0 0 1 .8 2H22v4h-1.8a7 7 0 0 1-.8 2z" />
  </svg>
);

const DashboardIcon = ({ size = 18 }: IconProps) => (
  <svg {...iconProps(size)}>
    <rect x="3" y="3" width="7" height="7" rx="1" />
    <rect x="14" y="3" width="7" height="4" rx="1" />
    <rect x="14" y="11" width="7" height="10" rx="1" />
    <rect x="3" y="12" width="7" height="9" rx="1" />
  </svg>
);

const Network = ({ size = 18 }: IconProps) => (
  <svg {...iconProps(size)}>
    <rect x="3" y="12" width="7" height="7" rx="2" />
    <rect x="14" y="10" width="7" height="9" rx="2" />
    <path d="M8 12l6-6 7 4" />
  </svg>
);

type Page = "Overview" | "Servers" | "Devices" | "Proxy" | "Settings";

type DashboardData = {
  server_count: number;
  device_count: number;
  network_status: string;
  connection_status: string;
};

type ServerData = {
  id?: string | number;
  name?: string;
  location?: string;
  status?: string;
};

type DeviceData = {
  id?: string | number;
  name?: string;
  platform?: string;
  status?: string;
};

export default function App() {
  const [page, setPage] = useState<Page>("Overview");
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [servers, setServers] = useState<ServerData[]>([]);
  const [devices, setDevices] = useState<DeviceData[]>([]);
  const [apiError, setApiError] = useState("");

  useEffect(() => {
    let active = true;

    const loadData = async () => {
      try {
        const responses = await Promise.all([
          fetch(`${API_BASE}/api/dashboard`),
          fetch(`${API_BASE}/api/servers`),
          fetch(`${API_BASE}/api/devices`),
        ]);

        if (responses.some((response) => !response.ok)) {
          throw new Error("Backend request failed");
        }

        const [dashboardData, serverData, deviceData] = await Promise.all(
          responses.map((response) => response.json())
        );

        if (!active) return;

        setDashboard(dashboardData);
        setServers(serverData.servers ?? []);
        setDevices(deviceData.devices ?? []);
        setApiError("");
      } catch {
        if (!active) return;
        setApiError("Cannot connect to the PHANTOM VPN backend.");
      }
    };

    loadData();

    const interval = window.setInterval(loadData, 15000);

    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, []);

  const navigation = [
    { name: "Overview", icon: DashboardIcon },
    { name: "Servers", icon: Globe },
    { name: "Devices", icon: Smartphone },
    { name: "Proxy", icon: Network },
    { name: "Settings", icon: Settings },
  ] as const;

  return (
    <div className="app">
      <aside className="sidebar">
        <h2>🛡 PHANTOM VPN</h2>
        <p className="label">WORKSPACE</p>

        {navigation.map(({ name, icon: Icon }) => (
          <button
            key={name}
            className={page === name ? "nav active" : "nav"}
            onClick={() => setPage(name)}
          >
            <Icon size={18} />
            {name}
          </button>
        ))}

        <div className="sidebar-footer">
          <Shield size={18} />
          Private Network
        </div>
      </aside>

      <main className="main">
        <header>
          <span>PHANTOM VPN / {page}</span>
          <span className="demo">DEVELOPMENT PREVIEW</span>
        </header>

        <section className="content">
          <h1>{page}</h1>
          <p className="subtitle">
            Manage your private VPN and proxy network.
          </p>

          {apiError && (
            <article className="card">
              <h3>Backend connection error</h3>
              <p>{apiError}</p>
            </article>
          )}

          {page === "Overview" && (
            <div className="grid">
              <article className="card connection">
                <Shield size={38} />
                <h2>
                  {dashboard?.connection_status ?? "Checking connection..."}
                </h2>
                <p>Your VPN tunnel has not been configured yet.</p>
                <button onClick={() => setPage("Servers")}>
                  Select server
                </button>
              </article>

              <article className="card">
                <Globe />
                <h3>Server locations</h3>
                <strong>
                  {dashboard ? `${dashboard.server_count} live nodes` : "Loading..."}
                </strong>
              </article>

              <article className="card">
                <Smartphone />
                <h3>Registered devices</h3>
                <strong>
                  {dashboard ? `${dashboard.device_count} devices` : "Loading..."}
                </strong>
              </article>

              <article className="card">
                <Server />
                <h3>Network status</h3>
                <strong>
                  {dashboard?.network_status ?? "Checking..."}
                </strong>
              </article>
            </div>
          )}

          {page === "Servers" && (
            <div className="card">
              <h2>VPN servers</h2>
              {servers.length === 0 ? (
                <p>No VPN servers registered yet.</p>
              ) : (
                servers.map((server, index) => (
                  <article key={server.id ?? index}>
                    <h3>{server.name ?? `Server ${index + 1}`}</h3>
                    <p>{server.location ?? "Location not specified"}</p>
                    <strong>{server.status ?? "Unknown status"}</strong>
                  </article>
                ))
              )}
            </div>
          )}

          {page === "Devices" && (
            <div className="card">
              <h2>Device management</h2>
              {devices.length === 0 ? (
                <p>No devices registered yet.</p>
              ) : (
                devices.map((device, index) => (
                  <article key={device.id ?? index}>
                    <h3>{device.name ?? `Device ${index + 1}`}</h3>
                    <p>{device.platform ?? "Platform not specified"}</p>
                    <strong>{device.status ?? "Unknown status"}</strong>
                  </article>
                ))
              )}
            </div>
          )}

          {page === "Proxy" && (
            <div className="card">
              <h2>Proxy management</h2>
              <p>No proxy endpoint is configured yet.</p>
            </div>
          )}

          {page === "Settings" && (
            <div className="card">
              <h2>Network settings</h2>
              <p>Security and network preferences.</p>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
