import type { Aspect, RenderRequest, TemplateChoice } from '@/lib/api/client'

export type RenderChoice = { template: TemplateChoice; aspects: Aspect[] }

export const renderBodyOf = (c: RenderChoice): RenderRequest => ({
  template: c.template,
  aspects: c.aspects,
})
