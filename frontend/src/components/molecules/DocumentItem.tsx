import Badge from '../atoms/Badge';
import Button from '../atoms/Button';
import type { DocumentMetadata } from '../../services/api';

type DocumentItemProps = {
  name: string;
  meta?: DocumentMetadata;
  actionLabel?: string;
  onRemove?: (name: string) => void;
};

export default function DocumentItem({
  name,
  meta,
  actionLabel = 'Remove',
  onRemove,
}: DocumentItemProps) {
  const extension = name.includes('.') ? name.split('.').pop() : 'file';

  return (
    <li className="document-item">
      <div>
        <p className="document-name">{name}</p>
        <div className="document-badges">
          <Badge>{extension}</Badge>
          {meta?.article_id ? <Badge tone="accent">{meta.article_id}</Badge> : null}
          {meta?.product_area ? <Badge>{meta.product_area}</Badge> : null}
        </div>
        {meta ? (
          <p className="document-meta">
            {meta.chunks} chunk{meta.chunks === 1 ? '' : 's'}
            {meta.last_updated && meta.last_updated !== 'unknown'
              ? ` · updated ${meta.last_updated}`
              : ''}
          </p>
        ) : null}
      </div>
      {onRemove ? (
        <Button variant="ghost" onClick={() => onRemove(name)}>
          {actionLabel}
        </Button>
      ) : null}
    </li>
  );
}
