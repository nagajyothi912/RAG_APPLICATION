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
}: RetrievalControlsProps) {
  // A document filter already implies its own product area, and ANDing the two
  // can silently retrieve nothing. Pinning one document wins; the area select
  // goes read-only rather than disappearing, so the rule stays visible.
  const areaLockedByDocument = Boolean(sourceFile);

  return (
    <div className="retrieval-controls">
      <ModeToggle
        value={mode}
        onChange={onModeChange}
        disabled={disabled}
        hybridAvailable={hybridAvailable}
        rerankerAvailable={rerankerAvailable}
      />

      <Select
        id="control-top-k"
        label="Top K"
        value={String(topK)}
        onChange={(value) => onTopKChange(Number(value))}
        disabled={disabled}
        hint="How many chunks are retrieved and passed to the model as context."
        options={TOP_K_CHOICES.map((k) => ({ value: String(k), label: String(k) }))}
      />

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
        label="Product area"
        value={areaLockedByDocument ? '' : productArea}
        onChange={onProductAreaChange}
        disabled={disabled || areaLockedByDocument || productAreas.length === 0}
        hint={
          areaLockedByDocument
            ? 'Set by the selected document.'
            : 'Answer only from chunks tagged with this product_area.'
        }
        options={[
          { value: '', label: areaLockedByDocument ? 'Set by document' : 'All areas' },
          ...productAreas.map((area) => ({ value: area, label: area })),
        ]}
      />
    </div>
  );
}
