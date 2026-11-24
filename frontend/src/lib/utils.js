import { clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

/** shadcn 约定的 class 合并工具：clsx 拼条件类名，tailwind-merge 去掉互相冲突的类 */
export function cn(...inputs) {
  return twMerge(clsx(inputs))
}