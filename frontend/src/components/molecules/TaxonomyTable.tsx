import type { AnalysisSummary } from '../../services/api';

type TaxonomyTableProps = {
  summary: AnalysisSummary;
  onPickMode: (mode: string) => void;
  activeMode?: string;
};

/**
 * The ranked failure modes, rendered from taxonomy.md via the API rather than
 * from a copy in the frontend - a second copy would drift from the file the
 * rubric is actually graded on.
 */
export default function TaxonomyTable({ summary, onPickMode, activeMode }: TaxonomyTableProps) {
  if (!summary.modes.length) {
    return (
      <p className="analysis-empty">
        No taxonomy found. Expected <code>docs/week5/taxonomy.md</code>.
      </p>
    );
  }

  return (
    <div className="taxonomy">
      <table className="taxonomy-table">
        <thead>
          <tr>
            <th scope="col">#</th>
            <th scope="col">Failure mode</th>
            <th scope="col" className="num">Count</th>
            <th scope="col" className="num">% of {summary.sample_size}</th>
            <th scope="col">Severity</th>
            <th scope="col">Example</th>
          </tr>
        </thead>
        <tbody>
          {summary.modes.map((mode) => {
            const isActive = activeMode === mode.name;
            return (
              <tr
                key={mode.rank}
                className={isActive ? 'is-active' : undefined}
                onClick={() => onPickMode(isActive ? '' : mode.name)}
                title="Filter the traces below by this mode"
              >
                <td className="num">{mode.rank}</td>
                <td>
                  <span className="mode-name">{mode.name}</span>
                  <span className="mode-bar" aria-hidden="true">
                    <span style={{ width: `${Math.max(mode.percent, 2)}%` }} />
                  </span>
                </td>
                <td className="num">{mode.count}</td>
                <td className="num">{mode.percent}%</td>
                <td>
                  <span
                    className={
                      mode.severity.startsWith('embarrass')
                        ? 'severity severity-high'
                        : 'severity severity-low'
                    }
                  >
                    {mode.severity}
                  </span>
                </td>
                <td>
                  <code>{mode.example_trace_id}</code>
                </td>
              </tr>
            );
          })}
          {summary.residual ? (
            <tr
              className={`residual${activeMode === summary.residual.name ? ' is-active' : ''}`}
              onClick={() =>
                onPickMode(activeMode === summary.residual!.name ? '' : summary.residual!.name)
              }
            >
              <td className="num">—</td>
              <td>{summary.residual.name}</td>
              <td className="num">{summary.residual.count}</td>
              <td className="num">{summary.residual.percent}%</td>
              <td />
              <td />
            </tr>
          ) : null}
        </tbody>
      </table>
      <p className="taxonomy-note">
        One trace is {summary.sample_size ? (100 / summary.sample_size).toFixed(0) : '5'} points, so
        modes separated by a single trace are within the noise of one draw. Click a row to filter.
      </p>
    </div>
  );
}
