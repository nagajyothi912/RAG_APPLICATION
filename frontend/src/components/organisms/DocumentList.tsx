import DocumentItem from '../molecules/DocumentItem';
import type { DocumentMetadata } from '../../services/api';

type DocumentListProps = {
  documents: string[];
  indexedChunks: number;
  metadata: DocumentMetadata[];
  /** Omitted for the chatbot role, which can read the library but not change it. */
  onDelete?: (name: string) => void;
  title?: string;
};

export default function DocumentList({
  documents,
  indexedChunks,
  metadata,
  onDelete,
  title = 'Indexed library',
}: DocumentListProps) {
  const byName = new Map(metadata.map((row) => [row.source_file, row]));

  return (
    <section className="indexed-documents">
      <header className="section-heading">
        <h2>{title}</h2>
        <p>
          {documents.length} document{documents.length === 1 ? '' : 's'} · {indexedChunks} chunk
          {indexedChunks === 1 ? '' : 's'}
        </p>
      </header>
      {documents.length === 0 ? (
        <p className="muted">
          {onDelete
            ? 'Nothing indexed yet. Answers will only come from files you upload.'
            : 'No articles are available yet.'}
        </p>
      ) : (
        <ul className="document-list">
          {documents.map((name) => (
            <DocumentItem
              key={name}
              name={name}
              meta={byName.get(name)}
              actionLabel="Delete"
              onRemove={onDelete}
            />
          ))}
        </ul>
      )}
    </section>
  );
}
