import { useRef, useState, type DragEvent } from 'react';
import Button from '../atoms/Button';

type FileSelectorProps = {
  onFilesChosen: (files: FileList | File[] | null) => void;
};

/**
 * A dropped folder arrives as a directory entry, not as files. Walk it and tag
 * each file with its path inside the drop, the same `webkitRelativePath` the
 * "Choose folder" picker sets, so folder uploads keep their relative paths
 * whichever way they were chosen.
 */
async function filesFromEntry(entry: FileSystemEntry, prefix = ''): Promise<File[]> {
  if (entry.isFile) {
    const file = await new Promise<File>((resolve, reject) =>
      (entry as FileSystemFileEntry).file(resolve, reject),
    );
    if (prefix) {
      Object.defineProperty(file, 'webkitRelativePath', { value: `${prefix}${file.name}` });
    }
    return [file];
  }
  if (!entry.isDirectory) {
    return [];
  }
  const reader = (entry as FileSystemDirectoryEntry).createReader();
  const children: FileSystemEntry[] = [];
  // readEntries returns at most ~100 entries per call; read until it is empty.
  for (;;) {
    const batch = await new Promise<FileSystemEntry[]>((resolve, reject) => reader.readEntries(resolve, reject));
    if (batch.length === 0) break;
    children.push(...batch);
  }
  const nested = await Promise.all(
    children.map((child) => filesFromEntry(child, `${prefix}${entry.name}/`)),
  );
  return nested.flat();
}

async function filesFromDrop(event: DragEvent<HTMLDivElement>): Promise<File[]> {
  const items = Array.from(event.dataTransfer.items ?? []);
  const entries = items
    .filter((item) => item.kind === 'file')
    .map((item) => item.webkitGetAsEntry?.())
    .filter((entry): entry is FileSystemEntry => Boolean(entry));
  if (entries.length === 0) {
    // No entry API: plain files only.
    return Array.from(event.dataTransfer.files);
  }
  const nested = await Promise.all(entries.map((entry) => filesFromEntry(entry)));
  return nested.flat();
}

export default function FileSelector({ onFilesChosen }: FileSelectorProps) {
  const filesRef = useRef<HTMLInputElement>(null);
  const folderRef = useRef<HTMLInputElement>(null);
  // dragenter/dragleave fire for every child the pointer crosses; count them so
  // the highlight only drops when the pointer really leaves the zone.
  const dragDepth = useRef(0);
  const [dragging, setDragging] = useState(false);
  const [dropError, setDropError] = useState<string | null>(null);

  const hasFiles = (event: DragEvent<HTMLDivElement>) => event.dataTransfer.types.includes('Files');

  return (
    <div
      className={`file-drop-zone ${dragging ? 'is-dragging' : ''}`}
      onDragEnter={(event) => {
        if (!hasFiles(event)) return;
        event.preventDefault();
        dragDepth.current += 1;
        setDragging(true);
      }}
      onDragOver={(event) => {
        if (!hasFiles(event)) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = 'copy';
      }}
      onDragLeave={(event) => {
        if (!hasFiles(event)) return;
        dragDepth.current = Math.max(0, dragDepth.current - 1);
        if (dragDepth.current === 0) setDragging(false);
      }}
      onDrop={(event) => {
        if (!hasFiles(event)) return;
        event.preventDefault();
        dragDepth.current = 0;
        setDragging(false);
        setDropError(null);
        filesFromDrop(event)
          .then((files) => {
            if (files.length) onFilesChosen(files);
            else setDropError('Nothing to add: the drop held no files.');
          })
          .catch(() => setDropError('Could not read the dropped items. Try Choose files instead.'));
      }}
    >
      <input
        ref={filesRef}
        className="visually-hidden"
        type="file"
        multiple
        accept=".txt,.md,.pdf,.json,text/plain,text/markdown,application/pdf,application/json"
        onChange={(event) => {
          onFilesChosen(event.target.files);
          event.target.value = '';
        }}
      />
      <input
        ref={(element) => {
          folderRef.current = element;
          if (element) {
            element.setAttribute('webkitdirectory', '');
            element.setAttribute('directory', '');
          }
        }}
        className="visually-hidden"
        type="file"
        multiple
        onChange={(event) => {
          onFilesChosen(event.target.files);
          event.target.value = '';
        }}
      />
      <p className="file-drop-hint">{dragging ? 'Drop to add' : 'Drag files or a folder here, or'}</p>
      <div className="file-selector">
        <Button variant="secondary" onClick={() => filesRef.current?.click()}>
          Choose files
        </Button>
        <Button variant="ghost" onClick={() => folderRef.current?.click()}>
          Choose folder
        </Button>
      </div>
      {dropError ? <p className="file-drop-error">{dropError}</p> : null}
    </div>
  );
}
