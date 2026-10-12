import { useEffect, useState } from 'react';
import { getAssistantServers, type McpDiscovery } from '../../services/api';
import Badge from '../atoms/Badge';
import StatusMessage from '../atoms/StatusMessage';

type McpServersPanelProps = {
  active: boolean;
  /** Omitted on the admin home, where the examples live in Common questions. */
  examples?: string[];
  onAsk?: (question: string) => void;
  disabled?: boolean;
};

/**
 * Admin Week 9 sidebar: what the assistant discovered over MCP (initialize +
 * tools/list on each server in config/mcp_servers.webapp.json), and example
 * questions that exercise each server.
 */
export default function McpServersPanel({ active, examples = [], onAsk, disabled = false }: McpServersPanelProps) {
  const [discovery, setDiscovery] = useState<McpDiscovery | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!active) return;
    getAssistantServers()
      .then((data) => {
        setDiscovery(data);
        setError(null);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Could not load MCP servers.'));
  }, [active]);

  return (
    <div className="help-sidebar">
      <section>
        <header className="section-heading">
          <h2>MCP servers</h2>
          <p>
            {discovery
              ? `${Object.keys(discovery.servers).length} servers · ${discovery.tool_count} tools from tools/list`
              : 'Discovered by the assistant at startup.'}
          </p>
        </header>
        <StatusMessage tone="error">{error}</StatusMessage>
        {discovery ? (
          <ul className="mcp-servers">
            {Object.entries(discovery.servers).map(([name, info]) => (
              <li key={name}>
                <div className="mcp-server-head">
                  <strong>{name}</strong>
                  <Badge>{info.transport}</Badge>
                </div>
                <p className="mcp-server-meta">
                  {info.server_name} · MCP {info.protocol_version}
                </p>
                <div className="mcp-tools">
                  {info.tools.map((tool) => (
                    <code key={tool}>{tool}</code>
                  ))}
                </div>
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      {examples.length && onAsk ? (
      <section className="help-questions">
        <header className="section-heading">
          <h2>Try</h2>
          <p>Each one exercises a different server or tool.</p>
        </header>
        <ul>
          {examples.map((question) => (
            <li key={question}>
              <button type="button" onClick={() => onAsk(question)} disabled={disabled}>
                {question}
              </button>
            </li>
          ))}
        </ul>
      </section>
      ) : null}
    </div>
  );
}
