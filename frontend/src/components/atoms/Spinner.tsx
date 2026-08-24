type SpinnerProps = {
  size?: 'sm' | 'md';
  label?: string;
};

export default function Spinner({ size = 'md', label = 'Loading' }: SpinnerProps) {
  return (
    <span className={`spinner spinner-${size}`} role="status" aria-label={label}>
      <span className="visually-hidden">{label}</span>
    </span>
  );
}
