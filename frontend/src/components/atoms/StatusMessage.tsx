import type { ReactNode } from 'react';

type StatusMessageProps = {
  tone?: 'info' | 'error' | 'success';
  children?: ReactNode;
};

export default function StatusMessage({ tone = 'info', children }: StatusMessageProps) {
  if (!children) {
    return null;
  }

  return (
    <p className={`status-message status-${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
      {children}
    </p>
  );
}
