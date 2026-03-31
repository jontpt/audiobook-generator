import React, { forwardRef } from 'react';
import { clsx } from 'clsx';

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  hint?: string;
  icon?: React.ReactNode;
  iconRight?: React.ReactNode;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(({
  label, error, hint, icon, iconRight, className, ...props
}, ref) => (
  <div className="flex flex-col gap-1.5">
    {label && (
      <label className="text-sm font-medium text-dark-200">
        {label}
        {props.required && <span className="text-brand-400 ml-1">*</span>}
      </label>
    )}
    <div className="relative">
      {icon && (
        <div className="absolute left-3 top-1/2 -translate-y-1/2 text-dark-400">
          {icon}
        </div>
      )}
      <input
        ref={ref}
        className={clsx(
          'w-full bg-dark-800 border rounded-xl text-white placeholder-dark-400',
          'focus:outline-none focus:ring-2 focus:ring-brand-500/50 focus:border-brand-500',
          'transition-all duration-200 py-2.5',
          icon    ? 'pl-10 pr-4' : 'px-4',
          iconRight ? 'pr-10' : '',
          error
            ? 'border-red-500/60 focus:ring-red-500/40 focus:border-red-500'
            : 'border-dark-700 hover:border-dark-600',
          className
        )}
        {...props}
      />
      {iconRight && (
        <div className="absolute right-3 top-1/2 -translate-y-1/2 text-dark-400">
          {iconRight}
        </div>
      )}
    </div>
    {error && <p className="text-xs text-red-400">{error}</p>}
    {hint && !error && <p className="text-xs text-dark-400">{hint}</p>}
  </div>
));
Input.displayName = 'Input';
