import os
import shutil
from pathlib import Path
from tqdm import tqdm
from typing import Callable
from .classes import Dataset, Caption, ImageInfo
from .utils import log_utils as logu


def run_tagger(
    source,
    save_path,
    save_every_n_steps=100,
    model_path=None,
    label_path=None,
    transform: Callable[[Caption, ImageInfo], Caption] = None,
    overwrite=False,
    device='cuda',
    verbose=False,
):
    from .compoents import WaifuTagger
    if overwrite:
        condition = None
    else:
        def condition(image_info): return image_info.caption is None
    dataset = Dataset(source, condition=condition)
    save_path = Path(save_path)
    save_path.parent.mkdir(parents=True, exist_ok=True)

    tagger = WaifuTagger(
        model_path=model_path,
        label_path=label_path,
        device=device,
        verbose=verbose,
    )

    pbar = tqdm(total=len(dataset), desc='Tagging')

    for i, item in enumerate(dataset.items()):
        image_key, image_info = item
        if image_info.caption is not None and not overwrite:
            pbar.update()
            continue
        pbar.set_postfix({'folder': image_info.image_path.parent.name, 'file': image_key})

        try:
            label = tagger(image_info.image_path)
        except Exception as e:
            logu.error(f"Error tagging {image_info.stem}: {e}")
            raise e

        caption = Caption(label)

        if transform:
            caption = transform(caption, image_info)

        dataset[image_key].caption = caption

        if i > 0 and i % save_every_n_steps == 0:
            pbar.write(f'step {i} | saving to `{logu.yellow(save_path)}`...')
            if save_path.suffix == '.csv':
                dataset.to_csv(save_path, mode='a')
            elif save_path.suffix == '.json':
                dataset.to_json(save_path, mode='a')

        pbar.update()

    if save_path.suffix == '.csv':
        dataset.to_csv(save_path, mode='a')
    elif save_path.suffix == '.json':
        dataset.to_json(save_path, mode='a')

    pbar.close()

    return dataset


def track_modification(
    dataset_a,
    dataset_b,
    track_move=True,
    track_remove=True,
):
    dataset_a = Dataset(dataset_a)
    dataset_b = Dataset(dataset_b)
    os_ops = {}
    for image_key, image_info_a in tqdm(dataset_a.items(), desc='Tracking modification'):
        image_info_a: ImageInfo
        img_path_a = image_info_a.image_path
        if track_move and image_key in dataset_b:
            image_info_b = dataset_b[image_key]
            category_a = image_info_a.category
            category_b = image_info_b.category
            if category_a != category_b:  # track category
                # move image file
                new_img_path_a = image_info_a.source / category_b / img_path_a.name
                new_img_path_a.parent.mkdir(parents=True, exist_ok=True)
                os_ops[image_key] = {
                    'op': 'move',
                    'src': str(img_path_a),
                    'dst': str(new_img_path_a),
                }
                # shutil.move(str(img_path_a), str(new_img_path_a))
                image_info_a.image_path = new_img_path_a

                # move caption file is exists
                cap_path_a = img_path_a.with_suffix('.txt')
                new_cap_path_a = new_img_path_a.with_suffix('.txt')
                if cap_path_a.exists():
                    os_ops[image_key + '_cap'] = {
                        'op': 'move',
                        'src': str(cap_path_a),
                        'dst': str(new_cap_path_a),
                    }
                    # shutil.move(str(cap_path_a), str(new_cap_path_a))
        elif track_remove and image_key not in dataset_b:
            # remove image file
            os_ops[image_key] = {
                'op': 'remove',
                'src': str(img_path_a),
            }
            # remove caption file is exists
            cap_path_a = img_path_a.with_suffix('.txt')
            if cap_path_a.exists():
                os_ops[image_key + '_cap'] = {
                    'op': 'remove',
                    'src': str(cap_path_a),
                }

    # record logs in a temp file and ask user to confirm
    if len(os_ops) == 0:
        logu.info('No modification detected.')
    else:
        logs = []
        for image_key, op in os_ops.items():
            op = op['op']
            if op == 'move':
                src = os_ops[image_key]['src']
                dst = os_ops[image_key]['dst']
                logs.append(f'move `{src}` to `{dst}`.')
            elif op == 'remove':
                src = os_ops[image_key]['src']
                logs.append(f'remove `{src}`.')
        log_path = Path('./.tmp/log.log')
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(logs))

        # ask user to confirm
        if input(f'Confirm to modify files according to `{log_path}`? (y/n) ').lower() == 'y':
            for image_key, op in tqdm(os_ops.items(), desc='Modifying files'):
                op = op['op']
                if op == 'move':
                    src = os_ops[image_key]['src']
                    dst = os_ops[image_key]['dst']
                    shutil.move(str(src), str(dst))
                elif op == 'remove':
                    src = os_ops[image_key]['src']
                    Path(src).unlink()
        else:
            logu.info('Operation canceled.')

        # remove temp file
        log_path.unlink()
        if len(os.listdir(log_path.parent)) == 0:
            log_path.parent.rmdir()

    logu.success('Done.')
