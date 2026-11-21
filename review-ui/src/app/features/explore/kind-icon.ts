import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import {
  LucideArrowLeftRight,
  LucideCheck,
  LucideCircleQuestionMark,
  LucideEye,
  LucideEyeOff,
  LucideLayers,
  LucideListChecks,
  LucideMap,
  LucideMapPin,
  LucideMessageSquare,
  LucidePlay,
  LucideRotate3d,
  LucideScanSearch,
  LucideSend,
  LucideStickyNote,
  LucideTriangleAlert,
  LucideZoomIn,
} from '@lucide/angular';
import { KindIcon } from './event-kind';

@Component({
  selector: 'app-kind-icon',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    LucideArrowLeftRight,
    LucideCheck,
    LucideCircleQuestionMark,
    LucideEye,
    LucideEyeOff,
    LucideLayers,
    LucideListChecks,
    LucideMap,
    LucideMapPin,
    LucideMessageSquare,
    LucidePlay,
    LucideRotate3d,
    LucideScanSearch,
    LucideSend,
    LucideStickyNote,
    LucideTriangleAlert,
    LucideZoomIn,
  ],
  template: `
    @switch (name()) {
      @case ('message') {
        <svg lucideMessageSquare [size]="size()" aria-hidden="true"></svg>
      }
      @case ('play') {
        <svg lucidePlay [size]="size()" aria-hidden="true"></svg>
      }
      @case ('eye') {
        <svg lucideEye [size]="size()" aria-hidden="true"></svg>
      }
      @case ('sweep') {
        <svg lucideRotate3d [size]="size()" aria-hidden="true"></svg>
      }
      @case ('zoom') {
        <svg lucideZoomIn [size]="size()" aria-hidden="true"></svg>
      }
      @case ('swap') {
        <svg lucideArrowLeftRight [size]="size()" aria-hidden="true"></svg>
      }
      @case ('confirm') {
        <svg lucideScanSearch [size]="size()" aria-hidden="true"></svg>
      }
      @case ('pin') {
        <svg lucideMapPin [size]="size()" aria-hidden="true"></svg>
      }
      @case ('check') {
        <svg lucideCheck [size]="size()" aria-hidden="true"></svg>
      }
      @case ('hidden') {
        <svg lucideEyeOff [size]="size()" aria-hidden="true"></svg>
      }
      @case ('checklist') {
        <svg lucideListChecks [size]="size()" aria-hidden="true"></svg>
      }
      @case ('layers') {
        <svg lucideLayers [size]="size()" aria-hidden="true"></svg>
      }
      @case ('map') {
        <svg lucideMap [size]="size()" aria-hidden="true"></svg>
      }
      @case ('note') {
        <svg lucideStickyNote [size]="size()" aria-hidden="true"></svg>
      }
      @case ('send') {
        <svg lucideSend [size]="size()" aria-hidden="true"></svg>
      }
      @case ('alert') {
        <svg lucideTriangleAlert [size]="size()" aria-hidden="true"></svg>
      }
      @default {
        <svg lucideCircleQuestionMark [size]="size()" aria-hidden="true"></svg>
      }
    }
  `,
  styles: `
    :host {
      display: inline-flex;
    }
  `,
})
export class KindIconView {
  readonly name = input.required<KindIcon>();
  readonly size = input(14);
}
