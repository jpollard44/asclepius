import PhotosUI
import SwiftUI
import UIKit

/// Camera / photo-library → /api/food/analyze → editable prefilled food form.
struct PhotoAnalysisView: View {
    let date: String
    let defaultMeal: String
    var onLogged: () -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var pickerItem: PhotosPickerItem?
    @State private var showCamera = false
    @State private var image: UIImage?
    @State private var analyzing = false
    @State private var form: FoodFormData?
    @State private var showForm = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            VStack(spacing: 20) {
                if let image {
                    Image(uiImage: image)
                        .resizable()
                        .scaledToFit()
                        .frame(maxHeight: 320)
                        .clipShape(RoundedRectangle(cornerRadius: 16))
                        .padding(.horizontal)
                } else {
                    EmptyState(
                        icon: "camera.viewfinder",
                        title: L.Food.photo,
                        message: L.Food.analysisNote)
                }

                if analyzing {
                    VStack(spacing: 8) {
                        ProgressView()
                        Text(L.Food.analyzing)
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                }

                HStack(spacing: 12) {
                    if UIImagePickerController.isSourceTypeAvailable(.camera) {
                        Button {
                            showCamera = true
                        } label: {
                            Label(L.Food.camera, systemImage: "camera.fill")
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.borderedProminent)
                    }
                    PhotosPicker(selection: $pickerItem, matching: .images) {
                        Label(L.Food.photoLibrary, systemImage: "photo.on.rectangle")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered)
                }
                .controlSize(.large)
                .padding(.horizontal)
                .disabled(analyzing)

                Spacer()
            }
            .padding(.top)
            .navigationTitle(L.Food.photo)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button(L.Common.cancel) { dismiss() }
                }
            }
            .onChange(of: pickerItem) { _, item in
                guard let item else { return }
                Task {
                    if let data = try? await item.loadTransferable(type: Data.self),
                       let loaded = UIImage(data: data) {
                        image = loaded
                        await analyze(loaded)
                    }
                }
            }
            .fullScreenCover(isPresented: $showCamera) {
                CameraPicker { captured in
                    image = captured
                    Task { await analyze(captured) }
                }
                .ignoresSafeArea()
            }
            .sheet(isPresented: $showForm, onDismiss: { form = nil }) {
                if let form {
                    AddFoodFormView(form: form) {
                        onLogged()
                        dismiss()
                    }
                }
            }
            .errorAlert(message: $errorMessage)
        }
    }

    private func analyze(_ image: UIImage) async {
        analyzing = true
        defer { analyzing = false }
        // Downscale for upload: the backend caps photos at 15 MB and the
        // model doesn't need full resolution.
        guard let data = image.resized(maxDimension: 1568).jpegData(compressionQuality: 0.8) else {
            errorMessage = L.Common.error
            return
        }
        do {
            let response = try await APIClient.shared.analyzeFoodPhoto(data)
            if let estimate = response.estimate {
                Haptics.success()
                form = FoodFormData(estimate: estimate, meal: defaultMeal, date: date)
                showForm = true
            } else {
                errorMessage = L.Common.error
            }
        } catch {
            errorMessage = (error as? APIError)?.errorDescription ?? L.Common.error
        }
    }
}

// MARK: - Camera wrapper

struct CameraPicker: UIViewControllerRepresentable {
    var onCapture: (UIImage) -> Void

    @Environment(\.dismiss) private var dismiss

    func makeUIViewController(context: Context) -> UIImagePickerController {
        let picker = UIImagePickerController()
        picker.sourceType = .camera
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ uiViewController: UIImagePickerController, context: Context) {}

    func makeCoordinator() -> Coordinator {
        Coordinator(self)
    }

    final class Coordinator: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
        private let parent: CameraPicker

        init(_ parent: CameraPicker) {
            self.parent = parent
        }

        func imagePickerController(
            _ picker: UIImagePickerController,
            didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]
        ) {
            if let image = info[.originalImage] as? UIImage {
                parent.onCapture(image)
            }
            parent.dismiss()
        }

        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) {
            parent.dismiss()
        }
    }
}

extension UIImage {
    /// Scales the image down so its longest side is at most `maxDimension`.
    func resized(maxDimension: CGFloat) -> UIImage {
        let longest = Swift.max(size.width, size.height)
        guard longest > maxDimension else { return self }
        let scaleFactor = maxDimension / longest
        let newSize = CGSize(width: size.width * scaleFactor, height: size.height * scaleFactor)
        let renderer = UIGraphicsImageRenderer(size: newSize)
        return renderer.image { _ in
            draw(in: CGRect(origin: .zero, size: newSize))
        }
    }
}
