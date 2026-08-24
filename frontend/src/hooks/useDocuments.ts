import { useCallback, useEffect, useState } from 'react';
import {
  ApiError,
  deleteDocument,
  listDocuments,
  uploadDocuments,
  type SkippedFile,
  type UploadStatusKind,
} from '../services/api';

export function useDocuments() {
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [documents, setDocuments] = useState<string[]>([]);
  const [indexedChunks, setIndexedChunks] = useState(0);
  const [status, setStatus] = useState<UploadStatusKind>('idle');
  const [error, setError] = useState<string | null>(null);
  const [skipped, setSkipped] = useState<SkippedFile[]>([]);

  const refresh = useCallback(async () => {
    try {
      const data = await listDocuments();
      setDocuments(data.documents);
      setIndexedChunks(data.indexed_chunks);
    } catch {
      // Listing is best-effort until the backend is up.
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const addFiles = useCallback((fileList: FileList | null) => {
    if (!fileList) {
      return;
    }
    const incoming = Array.from(fileList);
    setSelectedFiles((current) => {
      const byKey = new Map(current.map((file) => [file.webkitRelativePath || file.name, file]));
      for (const file of incoming) {
        byKey.set(file.webkitRelativePath || file.name, file);
      }
      return Array.from(byKey.values());
    });
    setError(null);
  }, []);

  const removeFile = useCallback((key: string) => {
    setSelectedFiles((current) =>
      current.filter((file) => (file.webkitRelativePath || file.name) !== key),
    );
  }, []);

  const clearSelected = useCallback(() => {
    setSelectedFiles([]);
  }, []);

  const removeIndexed = useCallback(async (name: string) => {
    setError(null);
    try {
      const result = await deleteDocument(name);
      setDocuments(result.documents);
      setIndexedChunks(result.indexed_chunks);
    } catch (err) {
      setStatus('error');
      setError(err instanceof Error ? err.message : 'Failed to delete document.');
    }
  }, []);

  const upload = useCallback(async () => {
    if (selectedFiles.length === 0) {
      setError('Select files or a folder first.');
      setStatus('error');
      return;
    }

    setStatus('uploading');
    setError(null);
    setSkipped([]);

    try {
      const result = await uploadDocuments(selectedFiles);
      setDocuments(result.documents);
      setIndexedChunks(result.indexed_chunks);
      setSkipped(result.skipped || []);
      setSelectedFiles([]);
      setStatus('success');
    } catch (err) {
      setStatus('error');
      setError(err instanceof Error ? err.message : 'Upload failed.');
      setSkipped(err instanceof ApiError ? err.extra?.skipped || [] : []);
    }
  }, [selectedFiles]);

  return {
    selectedFiles,
    documents,
    indexedChunks,
    status,
    error,
    skipped,
    addFiles,
    removeFile,
    removeIndexed,
    clearSelected,
    upload,
    refresh,
  };
}
