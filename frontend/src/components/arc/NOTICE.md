FileDropzone and motion tokens copied from Arc UI's free component registry:
https://uiarc.dev/r/file-dropzone.json
https://uiarc.dev/r/arc-motion-tokens.json

Component documentation: https://uiarc.dev/components/file-dropzone
Retrieved 25 October 2026. The documentation permits manual source installation.

Local integration changes: scoped black/pink/yellow theme tokens; disabled and
input-label props; single-file rejection; empty-file validation; failed selections
excluded from onFilesChange. The application submits the selected PDF together with
the interview settings when preparation is requested, without an immediate upload.
