import Button from '../atoms/Button';
import FileSelector from '../molecules/FileSelector';
import DocumentItem from '../molecules/DocumentItem';
import UploadStatus from '../molecules/UploadStatus';
import type { SkippedFile, UploadStatusKind } from '../../services/api';

type FileUploadProps = {
  selectedFiles: File[];
  status: UploadStatusKind;
  error: string | null;
  skipped: SkippedFile[];
  indexedChunks: number;
  onFilesChosen: (files: FileList | null) => void;
  onRemove: (name: string) => void;
  onClear: () => void;
  onUpload: () => void;
};

export default function FileUpload({
  selectedFiles,
  status,
  error,
  skipped,
  indexedChunks,
  onFilesChosen,
  onRemove,
  onClear,
  onUpload,
}: FileUploadProps) {
  return (
    <section className="file-upload">
      <header className="section-heading">
        <h2>Documents</h2>
        <p>Upload .txt, .md, or .pdf files. Folder upload keeps relative paths.</p>
      </header>
      <FileSelector onFilesChosen={onFilesChosen} />
      {selectedFiles.length > 0 ? (
        <ul className="document-list">
          {selectedFiles.map((file) => {
            const key = file.webkitRelativePath || file.name;
            return <DocumentItem key={key} name={key} onRemove={onRemove} />;
          })}
        </ul>
      ) : (
        <p className="muted">No files selected yet.</p>
      )}
      <div className="file-upload-actions">
        <Button onClick={onUpload} loading={status === 'uploading'} disabled={selectedFiles.length === 0}>
          Upload & index
        </Button>
        <Button variant="ghost" onClick={onClear} disabled={selectedFiles.length === 0}>
          Clear
        </Button>
      </div>
      <UploadStatus status={status} error={error} skipped={skipped} indexedChunks={indexedChunks} />
    </section>
  );
}
