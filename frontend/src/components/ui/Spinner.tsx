/**
 * src/components/ui/Spinner.tsx - Loading spinner component
 */

export function Spinner() {
  return (
    <div className="flex items-center justify-center">
      <div className="w-8 h-8 border-4 border-dark-secondary border-t-accent-blue rounded-full animate-spin" />
    </div>
  );
}

