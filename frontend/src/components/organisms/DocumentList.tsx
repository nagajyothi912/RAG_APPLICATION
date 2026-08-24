import DocumentItem from '../molecules/DocumentItem';

type DocumentListProps = {
  documents: string[];
  indexedChunks: number;
  onDelete: (name: string) => void;
};

export default function DocumentList({ documents, indexedChunks, onDelete }: DocumentListProps) {
  return (
    <section className="indexed-documents">
      <header className="section-heading">
        <h2>Indexed library</h2>
        <p>
          {documents.length} document{documents.length === 1 ? '' : 's'} · {indexedChunks} chunk
          {indexedChunks === 1 ? '' : 's'}
        </p>
      </header>
      {documents.length === 0 ? (
        <p className="muted">Nothing indexed yet. Answers will only come from files you upload.</p>
      ) : (
        <ul className="document-list">
          {documents.map((name) => (
            <DocumentItem key={name} name={name} actionLabel="Delete" onRemove={onDelete} />
          ))}
        </ul>
      )}
    </section>
  );
}
