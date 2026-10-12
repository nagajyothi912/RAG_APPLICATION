import type { ReactNode } from 'react';
import ModeToggle from '../atoms/ModeToggle';
import Select from '../atoms/Select';
import type { RetrievalMode } from '../../services/api';

type RetrievalControlsProps = {
  mode: RetrievalMode;
  onModeChange: (mode: RetrievalMode) => void;
  topK: number;
  onTopKChange: (topK: number) => void;
  productArea: string;
  onProductAreaChange: (area: string) => void;
  productAreas: string[];
  sourceFile: string;
  onSourceFileChange: (source: string) => void;
  documents: string[];
  disabled: boolean;
  hybridAvailable: boolean;
  rerankerAvailable: boolean;
  /** Off where the mode is fixed: the chatbot and the Week 3 tab. */
  showModeToggle?: boolean;
  /** Off in the chatbot, which uses the server's top-k. */
  showTopK?: boolean;
  areaLabel?: string;
  /** Display names for product areas; the raw value is still what is sent. */
  areaOptionLabel?: (area: string) => string;
  /** Rendered first in the row - the admin home's engine selector. */
  leading?: ReactNode;
};

const TOP_K_CHOICES = [1, 2, 3, 4, 5, 6, 8, 10];

export default function RetrievalControls({
  mode,
  onModeChange,
  topK,
  onTopKChange,
  productArea,
  onProductAreaChange,
  productAreas,
  sourceFile,
  onSourceFileChange,
  documents,
  disabled,
  hybridAvailable,
  rerankerAvailable,
  showModeToggle = true,
  showTopK = true,
  areaLabel = 'Product area',
  areaOptionLabel = (area: string) => area,
  leading = null,
}: RetrievalControlsProps) {
  // A document filter already implies its own product area, and ANDing the two
  // can silently retrieve nothing. Pinning one document wins; the area select
  // goes read-only rather than disappearing, so the rule stays visible.
  const areaLockedByDocument = Boolean(sourceFile);

  return (
    <div className="retrieval-controls">
      {leading}
      {showModeToggle ? (
        <ModeToggle
          value={mode}
          onChange={onModeChange}
          disabled={disabled}
          hybridAvailable={hybridAvailable}
          rerankerAvailable={rerankerAvailable}
        />
      ) : null}

      {showTopK ? (
        <Select
          id="control-top-k"
          label="Top K"
          value={String(topK)}
          onChange={(value) => onTopKChange(Number(value))}
          disabled={disabled}
          hint="How many chunks are retrieved and passed to the model as context."
          options={TOP_K_CHOICES.map((k) => ({ value: String(k), label: String(k) }))}
        />
      ) : null}

      {/* <Select
        id="control-document"
        label="Document"
        value={sourceFile}
        onChange={onSourceFileChange}
        disabled={disabled || documents.length === 0}
        hint="Answer only from this file."
        options={[
          { value: '', label: 'All documents' },
          ...documents.map((name) => ({ value: name, label: name })),
        ]}
      /> */}

      <Select
        id="control-product-area"
        label={areaLabel}
        value={areaLockedByDocument ? '' : productArea}
        onChange={onProductAreaChange}
        disabled={disabled || areaLockedByDocument || productAreas.length === 0}
        hint={
          areaLockedByDocument
            ? 'Set by the selected document.'
            : 'Answer only from chunks tagged with this product_area.'
        }
        options={[
          { value: '', label: areaLockedByDocument ? 'Set by document' : 'All topics' },
          ...productAreas.map((area) => ({ value: area, label: areaOptionLabel(area) })),
        ]}
      />
    </div>
  );
}
