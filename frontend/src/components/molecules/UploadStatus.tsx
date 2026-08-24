import StatusMessage from '../atoms/StatusMessage';
import Spinner from '../atoms/Spinner';
import type { SkippedFile, UploadStatusKind } from '../../services/api';

type UploadStatusProps = {
  status: UploadStatusKind;
  error: string | null;
  skipped: SkippedFile[];
  indexedChunks: number;
};

export default function UploadStatus({ status, error, skipped, indexedChunks }: UploadStatusProps) {
  if (status === 'uploading') {
    return (
      <div className="upload-status">
        <Spinner size="sm" label="Processing documents" />
        <StatusMessage tone="info">Uploading and indexing documents…</StatusMessage>
      </div>
    );
  }

  if (status === 'error') {
    return (
      <div className="upload-status">
        <StatusMessage tone="error">{error}</StatusMessage>
        {skipped.length > 0 ? (
          <ul className="skipped-list">
            {skipped.map((item) => (
              <li key={`${item.filename}-${item.reason}`}>
                {item.filename}: {item.reason}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    );
  }

  if (status === 'success') {
    return (
      <div className="upload-status">
        <StatusMessage tone="success">
          Documents indexed. {indexedChunks} chunk{indexedChunks === 1 ? '' : 's'} ready for retrieval.
        </StatusMessage>
        {skipped.length > 0 ? (
          <ul className="skipped-list">
            {skipped.map((item) => (
              <li key={`${item.filename}-${item.reason}`}>
                Skipped {item.filename}: {item.reason}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    );
  }

  return null;
}
