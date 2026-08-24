import Badge from '../atoms/Badge';
import Button from '../atoms/Button';

type DocumentItemProps = {
  name: string;
  actionLabel?: string;
  onRemove?: (name: string) => void;
};

export default function DocumentItem({ name, actionLabel = 'Remove', onRemove }: DocumentItemProps) {
  const extension = name.includes('.') ? name.split('.').pop() : 'file';

  return (
    <li className="document-item">
      <div>
        <p className="document-name">{name}</p>
        <Badge>{extension}</Badge>
      </div>
      {onRemove ? (
        <Button variant="ghost" onClick={() => onRemove(name)}>
          {actionLabel}
        </Button>
      ) : null}
    </li>
  );
}
