/// <reference types="vite/client" />

declare module "plotly.js-dist-min" {
  const Plotly: any;
  export default Plotly;
}

declare module "/static/ui/uploads.js" {
  export function createUploadsController(args: {
    uploadedListEl: HTMLElement;
    uploadsMetaEl: HTMLElement;
  }): {
    refreshUploadedList: () => Promise<any>;
    getSelectedSet: () => Set<string>;
    setSelectedSet: (s: Set<string>) => void;
    renderUploadList: () => void;
  };
}

