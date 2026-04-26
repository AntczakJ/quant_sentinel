import { motion, AnimatePresence } from 'framer-motion'

export function OfflineBanner({ show }: { show: boolean }) {
  return (
    <AnimatePresence>
      {show && (
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          className="border-b border-bear/30 bg-bear/[0.05]"
        >
          <div className="max-w-[1400px] mx-auto px-6 lg:px-10 py-3 flex items-center gap-3 text-caption">
            <span className="inline-block w-2 h-2 rounded-full bg-bear animate-pulse" />
            <span className="text-ink-800 font-medium">API offline.</span>
            <span className="text-ink-600">
              Start with{' '}
              <span className="font-mono">
                .venv/Scripts/python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000
              </span>
            </span>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
