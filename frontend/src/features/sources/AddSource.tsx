import { FileUp, Link2, Loader2 } from 'lucide-react'
import { useRef, useState, type DragEvent, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Button, Card, Progress } from '@/components/ui'
import { usePlatforms, useAddSource, useUploadSource } from '@/lib/sources'
import { cn } from '@/lib/utils'

type Mode = 'link' | 'file'

const ACCEPT = 'video/*,audio/*,.mkv,.flv,.ts,.wmv,.m4a,.opus,.flac'

function WindowFields({
  on,
  setOn,
  start,
  end,
  setStart,
  setEnd,
}: {
  on: boolean
  setOn: (v: boolean) => void
  start: string
  end: string
  setStart: (v: string) => void
  setEnd: (v: string) => void
}) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-wrap items-center gap-3 text-sm">
      <label className="flex items-center gap-2 text-muted">
        <input
          type="checkbox"
          checked={on}
          onChange={(e) => setOn(e.target.checked)}
          className="size-4 accent-accent"
        />
        {t('sources.add.partOnly')}
      </label>
      {on && (
        <>
          <input
            aria-label={t('sources.add.start')}
            placeholder={t('sources.add.startPh')}
            value={start}
            onChange={(e) => setStart(e.target.value)}
            className="h-8 w-28 rounded-md border border-border bg-surface-2 px-2"
          />
          <span className="text-muted">–</span>
          <input
            aria-label={t('sources.add.end')}
            placeholder={t('sources.add.endPh')}
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            className="h-8 w-28 rounded-md border border-border bg-surface-2 px-2"
          />
          <span className="text-xs text-muted">{t('sources.add.timeHelp')}</span>
        </>
      )}
    </div>
  )
}

export function AddSource() {
  const { t } = useTranslation()
  const [mode, setMode] = useState<Mode>('link')
  const [url, setUrl] = useState('')
  const [partOnly, setPartOnly] = useState(false)
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [pct, setPct] = useState(0)
  const [dragging, setDragging] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const add = useAddSource()
  const upload = useUploadSource()
  const platforms = usePlatforms()

  const win = partOnly ? { start: start || undefined, end: end || undefined } : {}
  const error = (mode === 'link' ? add.error : upload.error) as Error | null

  const done = (created: boolean) => {
    setNotice(created ? t('sources.add.added') : t('sources.add.already'))
    setUrl('')
    setPct(0)
  }

  const submitLink = (e: FormEvent) => {
    e.preventDefault()
    setNotice(null)
    if (!url.trim()) return
    add.mutate({ url: url.trim(), ...win }, { onSuccess: (r) => done(r.created) })
  }

  const sendFile = (file: File | undefined) => {
    if (!file) return
    setNotice(null)
    setPct(0)
    upload.mutate({ file, ...win, onProgress: setPct }, { onSuccess: (r) => done(r.created) })
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    sendFile(e.dataTransfer.files[0])
  }

  return (
    <Card className="p-5">
      <div className="mb-4 flex gap-1 rounded-lg bg-surface-2 p-1 text-sm" role="tablist">
        {(['link', 'file'] as const).map((m) => (
          <button
            key={m}
            role="tab"
            aria-selected={mode === m}
            onClick={() => {
              setMode(m)
              setNotice(null)
            }}
            className={cn(
              'flex flex-1 items-center justify-center gap-2 rounded-md py-1.5 transition',
              mode === m ? 'bg-surface font-medium shadow-sm' : 'text-muted hover:text-fg',
            )}
          >
            {m === 'link' ? <Link2 size={15} aria-hidden /> : <FileUp size={15} aria-hidden />}
            {t(`sources.add.${m}`)}
          </button>
        ))}
      </div>

      {mode === 'link' ? (
        <form onSubmit={submitLink} className="flex gap-2">
          <input
            type="url"
            inputMode="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder={t('sources.add.urlPh')}
            aria-label={t('sources.add.url')}
            className="h-9 min-w-0 flex-1 rounded-lg border border-border bg-surface-2 px-3 text-sm"
          />
          <Button type="submit" disabled={add.isPending || !url.trim()}>
            {add.isPending && <Loader2 size={14} className="animate-spin" aria-hidden />}
            {t('sources.add.submit')}
          </Button>
        </form>
      ) : (
        <div
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={cn(
            'flex flex-col items-center gap-2 rounded-lg border-2 border-dashed px-4 py-8 text-center text-sm',
            dragging ? 'border-accent bg-accent/5' : 'border-border',
          )}
        >
          <FileUp size={22} className="text-muted" aria-hidden />
          <p className="text-muted">{t('sources.add.drop')}</p>
          <Button
            variant="secondary"
            size="sm"
            disabled={upload.isPending}
            onClick={() => fileInput.current?.click()}
          >
            {t('sources.add.choose')}
          </Button>
          <input
            ref={fileInput}
            type="file"
            accept={ACCEPT}
            className="hidden"
            data-testid="file-input"
            onChange={(e) => {
              sendFile(e.target.files?.[0])
              e.target.value = ''
            }}
          />
          {upload.isPending && (
            <div className="mt-2 w-full max-w-sm">
              <Progress value={pct} />
              <p className="mt-1 text-xs text-muted">
                {t('sources.add.uploading', { pct: Math.round(pct) })}
              </p>
            </div>
          )}
        </div>
      )}

      <div className="mt-4">
        <WindowFields
          on={partOnly}
          setOn={setPartOnly}
          start={start}
          end={end}
          setStart={setStart}
          setEnd={setEnd}
        />
      </div>

      {error && (
        <p role="alert" className="mt-3 text-sm text-danger">
          {error.message}
        </p>
      )}
      {notice && !error && <p className="mt-3 text-sm text-ok">{notice}</p>}
      {mode === 'link' && platforms.data && (
        <p className="mt-3 text-xs text-muted">
          {t('sources.add.supported')} {platforms.data.map((p) => p.name).join(', ')}
        </p>
      )}
    </Card>
  )
}
