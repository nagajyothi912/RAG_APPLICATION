import { useRef } from 'react';
import Button from '../atoms/Button';

type FileSelectorProps = {
  onFilesChosen: (files: FileList | null) => void;
};

export default function FileSelector({ onFilesChosen }: FileSelectorProps) {
  const filesRef = useRef<HTMLInputElement>(null);
  const folderRef = useRef<HTMLInputElement>(null);

  return (
    <div className="file-selector">
      <input
        ref={filesRef}
        className="visually-hidden"
        type="file"
        multiple
        accept=".txt,.md,.pdf,text/plain,text/markdown,application/pdf"
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
      <Button variant="secondary" onClick={() => filesRef.current?.click()}>
        Choose files
      </Button>
      <Button variant="ghost" onClick={() => folderRef.current?.click()}>
        Choose folder
      </Button>
    </div>
  );
}
