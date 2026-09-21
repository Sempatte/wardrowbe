'use client';

import { useRef, useState } from 'react';
import Image from 'next/image';
import { useTranslations } from 'next-intl';
import { Loader2, Sparkles, Download, RotateCcw, Camera, Send, X } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { toast } from 'sonner';
import { useGenerateTryOn, useUploadBodyPhoto } from '@/lib/hooks/use-tryon';
import { useUserProfile } from '@/lib/hooks/use-user';
import { ApiError } from '@/lib/api';
// Structural subset shared by Item and OutfitItem — the dialog only needs
// enough to identify the piece and show a thumbnail, so it accepts either.
export interface TryOnItem {
  id: string;
  type: string;
  name?: string | null;
  thumbnail_url?: string;
}

interface TryOnDialogProps {
  items: TryOnItem[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function TryOnDialog({ items, open, onOpenChange }: TryOnDialogProps) {
  const t = useTranslations('tryon');
  const { data: profile } = useUserProfile();
  const uploadBodyPhoto = useUploadBodyPhoto();
  const generateTryOn = useGenerateTryOn();
  const [resultUrl, setResultUrl] = useState<string | null>(null);
  // Applied instructions (e.g. "no metas la camisa adentro del short"). Every
  // regeneration below re-sends the full list alongside item_ids - never the
  // previously generated image - so the model always starts fresh from the original
  // body photo + garment photos. Feeding a prior result back in would compound edits
  // and drift the person's face/body a little more with each round.
  const [comments, setComments] = useState<string[]>([]);
  const [commentDraft, setCommentDraft] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleClose = () => {
    onOpenChange(false);
    if (resultUrl) {
      URL.revokeObjectURL(resultUrl);
    }
    setResultUrl(null);
    setComments([]);
    setCommentDraft('');
  };

  const handleUploadBodyPhoto = async (file: File) => {
    try {
      await uploadBodyPhoto.mutateAsync(file);
    } catch {
      toast.error(t('errors.uploadFailed'));
    }
  };

  const runGenerate = async (commentsToApply: string[]) => {
    try {
      const url = await generateTryOn.mutateAsync({
        itemIds: items.map((item) => item.id),
        comments: commentsToApply,
      });
      if (resultUrl) {
        URL.revokeObjectURL(resultUrl);
      }
      setResultUrl(url);
    } catch (error) {
      if (error instanceof ApiError && error.status === 402) {
        toast.error(t('errors.quotaExceeded'));
      } else if (error instanceof ApiError && error.status === 400) {
        toast.error(t('errors.noBodyPhoto'));
      } else if (error instanceof ApiError && error.status === 401) {
        toast.error(t('errors.sessionExpired'));
      } else {
        toast.error(t('errors.generic'));
      }
    }
  };

  const handleGenerate = () => runGenerate(comments);

  const handleApplyComment = () => {
    const trimmed = commentDraft.trim();
    if (!trimmed || generateTryOn.isPending) return;
    const updated = [...comments, trimmed];
    setComments(updated);
    setCommentDraft('');
    runGenerate(updated);
  };

  const handleRemoveComment = (index: number) => {
    setComments((prev) => prev.filter((_, i) => i !== index));
  };

  const hasBodyPhoto = !!profile?.body_photo_url;

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-lg max-h-[90vh] flex flex-col">
        <DialogHeader className="flex-shrink-0">
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-primary" />
            {t('dialog.title')}
          </DialogTitle>
          <DialogDescription>{t('dialog.description')}</DialogDescription>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto overscroll-contain -mx-1 px-1">
        {!hasBodyPhoto ? (
          <div className="py-6 text-center space-y-4">
            <div className="w-16 h-16 rounded-full bg-muted mx-auto flex items-center justify-center">
              <Camera className="h-8 w-8 text-muted-foreground" />
            </div>
            <div>
              <p className="font-medium">{t('dialog.noBodyPhoto.title')}</p>
              <p className="text-sm text-muted-foreground mt-1">
                {t('dialog.noBodyPhoto.description')}
              </p>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/jpeg,image/png,image/webp,image/heic,image/heif"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleUploadBodyPhoto(file);
              }}
            />
            <Button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploadBodyPhoto.isPending}
            >
              {uploadBodyPhoto.isPending ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <Camera className="h-4 w-4 mr-2" />
              )}
              {t('dialog.noBodyPhoto.upload')}
            </Button>
          </div>
        ) : !resultUrl ? (
          <div className="space-y-4 py-2">
            <p className="text-sm font-medium text-muted-foreground">
              {t('dialog.selectedItems')}
            </p>
            <div className="flex flex-wrap gap-2">
              {items.map((item) => (
                <div
                  key={item.id}
                  className="w-16 h-16 rounded-lg bg-muted overflow-hidden relative border"
                >
                  {item.thumbnail_url ? (
                    <Image
                      src={item.thumbnail_url}
                      alt={item.name || item.type}
                      fill
                      className="object-cover"
                      sizes="64px"
                    />
                  ) : null}
                </div>
              ))}
            </div>
            {comments.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {comments.map((comment, index) => (
                  <Badge key={index} variant="secondary" className="font-normal">
                    {comment}
                  </Badge>
                ))}
              </div>
            )}
            {generateTryOn.isPending && (
              <p className="text-sm text-muted-foreground flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin" />
                {t('dialog.generating')}
              </p>
            )}
          </div>
        ) : (
          <div className="py-2 space-y-3">
            <div className="w-full rounded-lg overflow-hidden border bg-muted flex justify-center relative">
              {/* eslint-disable-next-line @next/next/no-img-element -- object URL blob, not a Next-optimizable remote src */}
              <img
                src={resultUrl}
                alt={t('dialog.title')}
                className="max-h-[55vh] w-auto object-contain"
              />
              {generateTryOn.isPending && (
                <div className="absolute inset-0 bg-background/70 flex items-center justify-center">
                  <Loader2 className="h-6 w-6 animate-spin text-primary" />
                </div>
              )}
            </div>
            <p className="text-xs text-muted-foreground">{t('dialog.resultDisclaimer')}</p>

            {comments.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {comments.map((comment, index) => (
                  <Badge key={index} variant="secondary" className="gap-1 pr-1 font-normal">
                    {comment}
                    <button
                      type="button"
                      onClick={() => handleRemoveComment(index)}
                      className="rounded-full hover:bg-muted-foreground/20 p-0.5"
                      aria-label={t('dialog.removeComment')}
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </Badge>
                ))}
              </div>
            )}

            <div className="flex gap-2">
              <Input
                value={commentDraft}
                onChange={(e) => setCommentDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    handleApplyComment();
                  }
                }}
                placeholder={t('dialog.commentPlaceholder')}
                disabled={generateTryOn.isPending}
                maxLength={300}
              />
              <Button
                type="button"
                size="icon"
                variant="outline"
                onClick={handleApplyComment}
                disabled={generateTryOn.isPending || !commentDraft.trim()}
                aria-label={t('dialog.applyComment')}
              >
                <Send className="h-4 w-4" />
              </Button>
            </div>
          </div>
        )}
        </div>

        <DialogFooter className="flex-shrink-0">
          {hasBodyPhoto && !resultUrl && (
            <>
              <Button variant="outline" onClick={handleClose}>
                {t('dialog.close')}
              </Button>
              <Button onClick={handleGenerate} disabled={generateTryOn.isPending}>
                {generateTryOn.isPending ? (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <Sparkles className="h-4 w-4 mr-2" />
                )}
                {t('dialog.generate')}
              </Button>
            </>
          )}
          {hasBodyPhoto && resultUrl && (
            <>
              <Button variant="outline" onClick={() => setResultUrl(null)}>
                <RotateCcw className="h-4 w-4 mr-2" />
                {t('dialog.regenerate')}
              </Button>
              <Button asChild>
                <a href={resultUrl} download="try-on.jpg">
                  <Download className="h-4 w-4 mr-2" />
                  {t('dialog.download')}
                </a>
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
